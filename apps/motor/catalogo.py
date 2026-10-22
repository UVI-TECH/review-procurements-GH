"""Catálogo de tipos como datos, y su resolvedor código/alias → tipo.

Se construye una vez por corrida (ADR 0002). Solo los tipos activos se resuelven: un
código de un tipo retirado se trata igual que uno desconocido.
"""

from dataclasses import dataclass

from .reglas import norm


@dataclass(frozen=True)
class TipoCatalogo:
    codigo: str
    etiqueta: str
    orden: int
    obligatorio: bool = True
    activo: bool = True
    requiere_firma: bool = False
    alias: tuple[str, ...] = ()


class Catalogo:
    def __init__(self, tipos):
        self.tipos = tuple(sorted(tipos, key=lambda t: (t.orden, t.codigo)))
        self.activos = tuple(t for t in self.tipos if t.activo)
        self._por_codigo = {}
        for tipo in self.activos:
            for codigo in (tipo.codigo, *tipo.alias):
                self._por_codigo[norm(codigo)] = tipo

    def resolver(self, codigo):
        """Devuelve el TipoCatalogo activo de un código o alias, o None."""
        return self._por_codigo.get(norm(codigo))

    @property
    def codigos_reconocidos(self):
        """Códigos y alias activos, en el orden del catálogo (estable para la caché)."""
        return tuple(c for t in self.activos for c in (t.codigo, *sorted(t.alias)))


def cargar_catalogo():
    """Adaptador delgado: lee el catálogo de la base de datos."""
    from apps.contrataciones.models import TipoDocumento

    return Catalogo(
        TipoCatalogo(
            codigo=t.codigo,
            etiqueta=t.etiqueta,
            orden=t.orden,
            obligatorio=t.obligatorio,
            activo=t.activo,
            requiere_firma=t.requiere_firma,
            alias=tuple(sorted(a.codigo for a in t.alias.all())),
        )
        for t in TipoDocumento.objects.prefetch_related("alias")
    )
