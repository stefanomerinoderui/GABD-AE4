"""Utilidades geográficas."""

import numpy as np

RADIO_TIERRA_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia de círculo máximo en km; acepta escalares o arreglos NumPy."""
    f1, f2 = np.radians(lat1), np.radians(lat2)
    dlat = f2 - f1
    dlon = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(f1) * np.cos(f2) * np.sin(dlon / 2) ** 2
    return 2 * RADIO_TIERRA_KM * np.arcsin(np.sqrt(a))
