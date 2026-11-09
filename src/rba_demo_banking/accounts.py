"""Each customer's own (made-up) accounts, the same every visit.

The demo used to show Martín's balances to every customer. Martín keeps the
figures the demo script and the screenshots use; anyone else gets accounts
drawn from a generator seeded by their user id, so two customers differ and
one customer sees the same page each time. Nothing here is real.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

MARTIN = "usr_rb_martin"

_SHOPS = (
    ("Supermercado Día", "Compra con débito", "S"),
    ("Coto", "Compra con débito", "C"),
    ("Farmacity", "Compra con débito", "F"),
    ("YPF", "Compra con débito", "Y"),
    ("Mercado Libre", "Compra con tarjeta", "ML"),
    ("Rappi", "Compra con tarjeta", "R"),
)
_BILLS = (
    ("Edesur", "Pago de servicio", "E"),
    ("Metrogas", "Pago de servicio", "M"),
    ("AySA", "Pago de servicio", "A"),
    ("Personal", "Pago de servicio", "P"),
    ("Netflix", "Suscripción", "N"),
    ("Spotify", "Suscripción", "S"),
)
_PEOPLE = ("Sofía Paz", "Lucía Gómez", "Tomás Ruiz", "Valentina Sosa", "Joaquín Díaz", "Camila Herrera")
_EMPLOYERS = ("Kaze Labs", "Estudio Marín", "Grupo Andes", "Hospital Italiano", "Municipalidad de Rosario")
_WHEN = ("Hoy", "Ayer", "Ayer", "3 nov", "1 nov", "30 oct", "28 oct")


@dataclass(frozen=True)
class Movement:
    who: str
    what: str
    when: str
    amount: float
    icon: str


@dataclass(frozen=True)
class Accounts:
    balances: tuple[tuple[str, str, float], ...]  # (name, masked number, amount)
    movements: tuple[Movement, ...]
    transfer_to: str
    transfer_account: str
    transfer_amount: float

    @property
    def total(self) -> float:
        return sum(amount for _, _, amount in self.balances)


_MARTIN = Accounts(
    balances=(("Caja de ahorro en pesos", "···· 4412", 248_320.15), ("Cuenta ahorro", "···· 9081", 1_502_000.00)),
    movements=(
        Movement("Supermercado Día", "Compra con débito", "Hoy", -12_430.00, "S"),
        Movement("Sofía Paz", "Transferencia recibida", "Ayer", 25_000.00, "SP"),
        Movement("Edesur", "Pago de servicio", "Ayer", -18_760.40, "E"),
        Movement("Sueldo · Kaze Labs", "Acreditación", "1 oct", 1_180_000.00, "K"),
        Movement("Spotify", "Suscripción", "30 sep", -4_299.00, "S"),
    ),
    transfer_to="Sofía Paz",
    transfer_account="···· 9081",
    transfer_amount=12_500.00,
)


def _initials(name: str) -> str:
    return "".join(part[0] for part in name.split()[:2]).upper()


def accounts_for(user_id: str) -> Accounts:
    if user_id == MARTIN:
        return _MARTIN
    rng = random.Random(int.from_bytes(hashlib.sha256(user_id.encode()).digest()[:8], "big"))
    masked = lambda: f"···· {rng.randint(1000, 9999)}"  # noqa: E731
    balances = [("Caja de ahorro en pesos", masked(), round(rng.uniform(15_000, 900_000), 2))]
    if rng.random() < 0.6:
        balances.append(("Cuenta corriente en pesos", masked(), round(rng.uniform(5_000, 400_000), 2)))
    if rng.random() < 0.5:
        balances.append(("Plazo fijo", masked(), round(rng.uniform(200_000, 3_000_000), -3)))

    friend = rng.choice(_PEOPLE)
    pool = [
        *(Movement(who, what, "", -round(rng.uniform(2_000, 60_000), 2), icon) for who, what, icon in rng.sample(_SHOPS, 2)),
        *(Movement(who, what, "", -round(rng.uniform(3_000, 35_000), 2), icon) for who, what, icon in rng.sample(_BILLS, 2)),
        Movement(friend, "Transferencia recibida", "", round(rng.uniform(5_000, 80_000), -2), _initials(friend)),
    ]
    rng.shuffle(pool)
    employer = rng.choice(_EMPLOYERS)
    salary = Movement(f"Sueldo · {employer}", "Acreditación", "1 nov", round(rng.uniform(600_000, 2_400_000), -3), _initials(employer))
    dated = [Movement(m.who, m.what, when, m.amount, m.icon) for m, when in zip(pool, _WHEN)]
    movements = tuple(sorted([*dated[:4], salary], key=lambda m: _WHEN.index(m.when) if m.when in _WHEN else 4))
    payee = rng.choice([p for p in _PEOPLE if p != friend])
    return Accounts(
        balances=tuple(balances),
        movements=movements,
        transfer_to=payee,
        transfer_account=masked(),
        transfer_amount=round(rng.uniform(5_000, 40_000), -2),
    )
