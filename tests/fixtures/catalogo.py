"""Catálogo sintético igual al sembrado en la Fase 1, sin base de datos."""

from apps.motor.catalogo import Catalogo, TipoCatalogo

DOCS = [
    ("certificado_antecedentes_disciplinarios", "Antecedentes Disciplinarios (Procuraduría)"),
    ("boletin_responsabilidades_fiscales", "Responsabilidades Fiscales (Contraloría)"),
    ("certificado_antecedentes_judiciales", "Antecedentes Judiciales (Policía)"),
    ("certificado_registro_nacional_medidas_correctivas", "Medidas Correctivas"),
    ("formato_autorizacion_consulta_inhabilidades", "Formato Autorización Consulta"),
    ("consulta_inhabilidades_delitos_sexuales", "Consulta Inhabilidades Delitos Sexuales"),
    ("certificado_registro_deudores_morosos", "REDAM (Deudores Morosos)"),
    ("certificados_eps_afp", "Certificados EPS/AFP"),
    ("certificado_medico_laboral", "Certificado Médico Laboral"),
]
CODIGOS = [codigo for codigo, _ in DOCS]
FORMATO = "formato_autorizacion_consulta_inhabilidades"
MEDICO = "certificado_medico_laboral"
DOTC = "examen_medico_laboral_dotc"


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
                "alias": (DOTC,) if codigo == MEDICO else (),
                **cambios.get(codigo, {}),
            }
        )
        for orden, (codigo, etiqueta) in enumerate(DOCS, start=1)
    ]


def catalogo_inicial(**cambios):
    return Catalogo(tipos_iniciales(**cambios))
