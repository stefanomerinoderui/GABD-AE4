"""Minería de datos (KDD / CRISP-DM) sobre el data warehouse.

* Predictivo: regresión lineal para estimar el ETA de un envío.
* Descriptivo: DBSCAN y K-Means espaciales sobre los incidentes (puntos calientes).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from logistica.conexiones import conectar_pg
from logistica.geo import RADIO_TIERRA_KM

CARACTERISTICAS_NUMERICAS = [
    "distancia_km",
    "indice_trafico",
    "lluvia_mm",
    "peso_kg",
    "hora_despacho",
]
CARACTERISTICAS_CATEGORICAS = ["region_origen", "tipo_vehiculo"]


def cargar_entregas() -> pd.DataFrame:
    """Fase CRISP-DM 'Comprensión/Preparación de los datos': vista plana del DW."""
    with conectar_pg("dw") as dw:
        filas = dw.execute(
            """
            SELECT h.envio_id, h.distancia_km, h.indice_trafico, h.lluvia_mm, h.peso_kg,
                   h.hora_despacho, h.horas_entrega, g.region AS region_origen,
                   coalesce(v.tipo, 'sin_asignar') AS tipo_vehiculo, t.anio
            FROM hechos_entregas h
            JOIN dim_geografia g ON g.geografia_id = h.geografia_origen_id
            JOIN dim_tiempo t ON t.tiempo_id = h.tiempo_id
            LEFT JOIN dim_vehiculo v ON v.vehiculo_id = h.vehiculo_id
            """
        ).fetchall()
    return pd.DataFrame(filas).astype(
        {c: float for c in [*CARACTERISTICAS_NUMERICAS, "horas_entrega"]}
    )


@dataclass
class ResultadoEta:
    modelo: Pipeline
    mae_horas: float
    r2: float
    mae_base_horas: float
    coeficientes: pd.Series


def entrenar_eta(datos: pd.DataFrame, semilla: int = 42) -> ResultadoEta:
    """Fase 'Modelado' y 'Evaluación' del ETA con regresión lineal.

    El conjunto se parte 80/20 para evaluar sobre datos no vistos. La línea base
    es predecir siempre la media: el modelo solo es útil si la supera.
    """
    if len(datos) < 50:
        raise ValueError(f"Datos insuficientes para entrenar ({len(datos)} filas)")
    x = datos[CARACTERISTICAS_NUMERICAS + CARACTERISTICAS_CATEGORICAS]
    y = datos["horas_entrega"]
    x_ent, x_test, y_ent, y_test = train_test_split(x, y, test_size=0.2, random_state=semilla)

    preprocesado = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore"), CARACTERISTICAS_CATEGORICAS)],
        remainder="passthrough",
    )
    modelo = Pipeline([("prep", preprocesado), ("reg", LinearRegression())])
    modelo.fit(x_ent, y_ent)
    prediccion = modelo.predict(x_test)

    coeficientes = pd.Series(
        modelo.named_steps["reg"].coef_,
        index=modelo.named_steps["prep"].get_feature_names_out(),
    ).sort_values(key=abs, ascending=False)
    return ResultadoEta(
        modelo=modelo,
        mae_horas=mean_absolute_error(y_test, prediccion),
        r2=r2_score(y_test, prediccion),
        mae_base_horas=mean_absolute_error(y_test, np.full(len(y_test), y_ent.mean())),
        coeficientes=coeficientes,
    )


def cargar_incidentes() -> pd.DataFrame:
    with conectar_pg("dw") as dw:
        filas = dw.execute(
            """
            SELECT h.incidente_id, h.lat, h.lon, h.demora_min, h.tipo, g.region
            FROM hechos_incidentes h JOIN dim_geografia g ON g.geografia_id = h.geografia_id
            """
        ).fetchall()
    return pd.DataFrame(filas).astype({"lat": float, "lon": float, "demora_min": float})


def detectar_puntos_calientes(
    incidentes: pd.DataFrame, radio_km: float = 25.0, minimo_incidentes: int = 15
) -> pd.DataFrame:
    """DBSCAN con distancia haversine: agrupa por densidad y marca ruido (-1).

    No exige fijar el número de clusters y descarta los incidentes aislados,
    que es lo que interesa para detectar zonas críticas.
    """
    coordenadas = np.radians(incidentes[["lat", "lon"]].to_numpy())
    modelo = DBSCAN(
        eps=radio_km / RADIO_TIERRA_KM,
        min_samples=minimo_incidentes,
        metric="haversine",
        algorithm="ball_tree",
    )
    return incidentes.assign(cluster=modelo.fit_predict(coordenadas))


def resumir_clusters(etiquetados: pd.DataFrame) -> pd.DataFrame:
    """Tamaño, demora promedio y centroide de cada cluster (sin contar el ruido)."""
    return (
        etiquetados[etiquetados["cluster"] >= 0]
        .groupby("cluster")
        .agg(
            incidentes=("incidente_id", "count"),
            demora_media_min=("demora_min", "mean"),
            lat=("lat", "mean"),
            lon=("lon", "mean"),
        )
        .sort_values("incidentes", ascending=False)
        .round(2)
    )


def candidatos_centros_transferencia(
    incidentes: pd.DataFrame, k: int, semilla: int = 42
) -> pd.DataFrame:
    """K-Means sobre coordenadas: los centroides son ubicaciones candidatas para
    nuevos centros de transferencia (edge). Se devuelve también la inercia, útil
    para elegir `k` con el método del codo."""
    modelo = KMeans(n_clusters=k, n_init=10, random_state=semilla)
    modelo.fit(incidentes[["lat", "lon"]])
    centros = pd.DataFrame(modelo.cluster_centers_, columns=["lat", "lon"]).round(3)
    centros["incidentes"] = np.bincount(modelo.labels_, minlength=k)
    centros.attrs["inercia"] = modelo.inertia_
    return centros


def inercia_por_k(incidentes: pd.DataFrame, rango=range(1, 11)) -> pd.Series:
    return pd.Series(
        {k: candidatos_centros_transferencia(incidentes, k).attrs["inercia"] for k in rango},
        name="inercia",
    )
