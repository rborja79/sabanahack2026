"""Errores del andamio. Cada uno puede traer una pista de que hacer."""


class ErrorAndamio(Exception):
    pista = ""

    def __init__(self, mensaje="", pista=None):
        super().__init__(mensaje)
        if pista is not None:
            self.pista = pista


class ErrorConexion(ErrorAndamio):
    """No se pudo hablar con el robot o con un servicio necesario."""


class ErrorRobot(ErrorAndamio):
    """El robot rechazo una orden o respondio con un fallo."""


class NoSoportado(ErrorRobot):
    """Este robot no sabe hacer lo que se pide."""


class ErrorSeguridad(ErrorAndamio):
    """Una regla de seguridad impidio o interrumpio la accion."""


class ErrorPlantilla(ErrorAndamio):
    """La plantilla esta mal escrita."""


class ErrorVoz(ErrorAndamio):
    """Fallo en el oido, el entendimiento o el habla."""


class ErrorConfiguracion(ErrorAndamio):
    """Un valor de config.yaml o de una variable de entorno no es valido."""
