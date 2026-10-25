"""Catálogo sintético igual al de las migraciones (0002 y 0008), sin base de datos."""

from apps.motor.catalogo import AliasCatalogo, Catalogo, TipoCatalogo

DOCS = [
    ("certificado_antecedentes_disciplinarios", "Antecedentes Disciplinarios (Procuraduría)"),
    ("boletin_responsabilidades_fiscales", "Responsabilidades Fiscales (Contraloría)"),
    ("certificado_antecedentes_judiciales", "Antecedentes Judiciales (Policía)"),
    ("certificado_registro_nacional_medidas_correctivas", "Medidas Correctivas"),
    ("formato_autorizacion_consulta_inhabilidades", "Formato Autorización Consulta"),
    ("consulta_inhabilidades_delitos_sexuales", "Consulta Inhabilidades Delitos Sexuales"),
    ("certificado_registro_deudores_morosos", "REDAM (Deudores Morosos)"),
    ("certificado_eps", "Certificado de EPS"),
    ("certificado_afp", "Certificado de fondo de pensiones (AFP)"),
    ("certificado_medico_laboral", "Certificado Médico Laboral"),
]
CODIGOS = [codigo for codigo, _ in DOCS]
FORMATO = "formato_autorizacion_consulta_inhabilidades"
MEDICO = "certificado_medico_laboral"
DOTC = "examen_medico_laboral_dotc"
EPS = "certificado_eps"
AFP = "certificado_afp"
PENSION = "resolucion_pension_vejez"
BONO = "carta_bono_pensional"
OBS_BONO = "Carta de bono pensional: declaración del profesor, no certificado de una entidad"
SIN_VIGENCIA = {FORMATO, MEDICO}

ALIAS = {
    MEDICO: (AliasCatalogo(DOTC, etiqueta="Examen médico laboral DOTC"),),
    AFP: (
        AliasCatalogo(
            BONO, etiqueta="Carta de bono pensional", hereda_vigencia=False, observacion=OBS_BONO
        ),
        AliasCatalogo(
            PENSION,
            etiqueta="Resolución o certificado de pensión por vejez",
            hereda_vigencia=False,
        ),
    ),
}


def tipos_iniciales(**cambios):
    """cambios: {codigo: {campo: valor}} para variar obligatorio, activo, etc."""
    return [
        TipoCatalogo(
            **{
                "codigo": codigo,
                "etiqueta": etiqueta,
                "orden": orden,
                "obligatorio": True,
                "activo": True,
                "requiere_firma": codigo == FORMATO,
                "alias": tuple(a.codigo for a in ALIAS.get(codigo, ())),
                "detalle_alias": ALIAS.get(codigo, ()),
                "vigencia_dias": None if codigo in SIN_VIGENCIA else 30,
                **cambios.get(codigo, {}),
            }
        )
        for orden, (codigo, etiqueta) in enumerate(DOCS, start=1)
    ]


def catalogo_inicial(**cambios):
    return Catalogo(tipos_iniciales(**cambios))
