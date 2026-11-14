"""Consultas de análisis que devuelven DataFrames de pandas."""

from decimal import Decimal

import pandas as pd

from logistica.conexiones import conectar_pg


def consultar(nodo: str, consulta: str, parametros=None) -> pd.DataFrame:
    """Ejecuta una consulta de solo lectura en `nodo` y devuelve el resultado.

    Las columnas `numeric` de PostgreSQL llegan como `Decimal`; se convierten a
    `float` para poder operar y graficar con pandas.
    """
    with conectar_pg(nodo) as conexion:
        filas = conexion.execute(consulta, parametros).fetchall()
    datos = pd.DataFrame(filas)
    for columna in datos.select_dtypes(include="object").columns:
        if datos[columna].map(lambda v: isinstance(v, Decimal)).any():
            datos[columna] = datos[columna].astype(float)
    return datos
