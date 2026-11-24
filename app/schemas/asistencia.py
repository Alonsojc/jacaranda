"""Local staff schedules."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

HoraLocal = Annotated[str, StringConstraints(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]
DiaSemana = Annotated[Literal["0", "1", "2", "3", "4", "5", "6"], Field(description="Lunes = 0")]
Modalidad = Literal["sucursal", "compras"]
NotaHorario = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300, pattern=r"^[^\x00]*$")]
NombreHorario = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100,
                                                 pattern=r"^[^\x00-\x1f\x7f]+$")]
NumeroReloj = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80,
                                               pattern=r"^[^\x00-\x1f\x7f]+$")]


class PersonaHorarioCreate(BaseModel):
    nombre: NombreHorario
    numero_reloj: NumeroReloj | None = None


class RelojHorarioSave(BaseModel):
    numero_reloj: NumeroReloj


class HorasTurno(BaseModel):
    entrada: HoraLocal
    salida: HoraLocal

    @model_validator(mode="after")
    def validar_intervalo(self) -> Self:
        if self.salida <= self.entrada:
            raise ValueError("La salida debe ser posterior a la entrada en el mismo día.")
        return self


class HorarioSemanalSave(BaseModel):
    vigente_desde: date
    dias: dict[DiaSemana, HorasTurno]
    modalidad: Modalidad = "sucursal"
    nota: NotaHorario = ""


class TurnoFechaSave(BaseModel):
    tipo: Literal["apoyo", "cobertura", "ajuste", "descanso"]
    horas: HorasTurno | None = None
    modalidad: Modalidad = "sucursal"
    nota: NotaHorario = ""

    @model_validator(mode="after")
    def validar_horas(self) -> Self:
        if (self.horas is None) != (self.tipo == "descanso"):
            raise ValueError("Indica entrada y salida para los turnos de trabajo.")
        return self
