"""Catálogo de tipos como datos, y su resolvedor código/alias → tipo.

Se construye una vez por corrida (ADR 0002). Solo los tipos activos se resuelven: un
código de un tipo retirado se trata igual que uno desconocido.
"""

from dataclasses import dataclass

from .reglas import norm


@dataclass(frozen=True)
class AliasCatalogo:
    """Un alias con datos propios: con qué documento se cumplió el requisito (ADR 0006)."""

    codigo: str
    etiqueta: str = ""  # vacío: la del tipo
    hereda_vigencia: bool = True
    vigencia_dias: int | None = None
    observacion: str = ""


@dataclass(frozen=True)
class TipoCatalogo:
    codigo: str
    etiqueta: str
    orden: int
    obligatorio: bool = True
    activo: bool = True
    requiere_firma: bool = False
    alias: tuple[str, ...] = ()
    vigencia_dias: int | None = None  # None: no vence
    requiere_logo: bool = False  # aún sin regla (ADR 0006)
    detalle_alias: tuple[AliasCatalogo, ...] = ()  # solo los alias con datos propios


class Catalogo:
    def __init__(self, tipos):
        self.tipos = tuple(sorted(tipos, key=lambda t: (t.orden, t.codigo)))
        self.activos = tuple(t for t in self.tipos if t.activo)
        self._por_codigo = {}
        self._alias = {}
        for tipo in self.activos:
            for codigo in (tipo.codigo, *tipo.alias):
                self._por_codigo[norm(codigo)] = tipo
            for detalle in tipo.detalle_alias:
                self._alias[norm(detalle.codigo)] = detalle

    def resolver(self, codigo):
        """Devuelve el TipoCatalogo activo de un código o alias, o None."""
        return self._por_codigo.get(norm(codigo))

    def etiqueta_de(self, codigo):
        """La etiqueta del alias si tiene una propia; si no, la del tipo. None si no resuelve."""
        tipo = self.resolver(codigo)
        if tipo is None:
            return None
        alias = self._alias.get(norm(codigo))
        return (alias.etiqueta if alias else "") or tipo.etiqueta

    def vigencia_de(self, codigo):
        """Días de vigencia de un código o alias; None si no vence o no resuelve."""
        tipo = self.resolver(codigo)
        if tipo is None:
            return None
        alias = self._alias.get(norm(codigo))
        if alias and not alias.hereda_vigencia:
            return alias.vigencia_dias
        return tipo.vigencia_dias

    def observacion_de(self, codigo):
        alias = self._alias.get(norm(codigo))
        return alias.observacion if alias and self.resolver(codigo) else ""

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
            vigencia_dias=t.vigencia_dias,
            requiere_logo=t.requiere_logo,
            detalle_alias=tuple(
                AliasCatalogo(
                    codigo=a.codigo,
                    etiqueta=a.etiqueta,
                    hereda_vigencia=a.hereda_vigencia,
                    vigencia_dias=a.vigencia_dias,
                    observacion=a.observacion,
                )
                for a in sorted(t.alias.all(), key=lambda a: a.codigo)
            ),
        )
        for t in TipoDocumento.objects.prefetch_related("alias")
    )
