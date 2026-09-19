"""RODO erasure that survives a re-import (F9 follow-up).

Erasing a client must (1) leave no personal data behind, (2) not cost the performer
her commission, and (3) not be undone by the next Booksy sync. So:

* her VISITS are kept but anonymised — re-pointed at one shared placeholder client,
  notes wiped. Date / service / amount / performer are the salon's own business
  records and keep the commission and the statistics intact. Anonymisation is
  STICKY BY IDENTITY: the visit import looks a row up by its Booksy reference first
  and never moves a visit off the placeholder, whatever name or date the report
  carries (renamed clients, other spellings, bookings in the future);
* her NAME is scrubbed from the text columns that do not hang off the client row
  (till rows, packages, package redemptions, vouchers);
* a SUPPRESSION entry remembers her — as a salted hash, never the name — with the
  erasure date, for records we have never seen before (an old month imported for
  the first time). It only covers records dated ON OR BEFORE the erasure, so a
  later namesake, or the same person returning under a new consent, is a normal
  new client.

LIVE NAMESAKE WINS. Names collide ("Anna Nowak"). While another real client carries
the same name we can not tell whose an unlinked record is, and silently anonymising
an active client's history, package or voucher (her money) is the worse failure.
So with a live namesake: no name-level suppression entry is written and only
records LINKED to the erased client are scrubbed. The till rows are the exception —
scrubbed regardless, because the only cost of a wrong guess there is a missing
performer hint.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    Client,
    ErasedName,
    Package,
    PackageRedemption,
    RegisterTxn,
    Visit,
    Voucher,
)

ANON_FIRST, ANON_LAST = "Klientka usunięta", "(RODO)"
ANON_NAME = f"{ANON_FIRST} {ANON_LAST}"

_EDGE_PUNCT = " \t,.;:()[]{}\"'„”"


def name_tokens(*parts: str | None) -> list[str]:
    """Lower-cased words of a name. Hyphenated surnames stay ONE token, so
    "Kowalska" never matches "Kowalska-Nowak"; the import placeholder "?" is dropped."""
    words = re.split(r"\s+", " ".join(p or "" for p in parts).lower())
    tokens = [w.strip(_EDGE_PUNCT) for w in words]
    return [t for t in tokens if t and t != "?" and t not in ("-", "—", "–")]


def name_key(*parts: str | None) -> str:
    """Order-independent identity of a name: Booksy writes "First Last", some
    exports "Last First", our own rows keep the two apart."""
    return " ".join(sorted(name_tokens(*parts)))


def _digest(salt: str, key: str) -> str:
    return hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()


def _freetext_names(text: str | None, size: int) -> set[str]:
    """Every `size`-word name a hand-typed cell could be carrying: its runs of `size`
    ADJACENT words ("prezent dla: Kowalska Anna" → {"dla prezent", "dla kowalska",
    "anna kowalska"}). Adjacent, not any pair — "Anna Nowak, Ewa Kowalska" names two
    people, neither of whom is "Anna Kowalska". A single-word name only ever matches
    a cell that IS that word: "Anna" must not swallow every "Anna Kowalska"."""
    tokens = name_tokens(text)
    if size < 2:
        return {" ".join(sorted(tokens))} if tokens else set()
    return {" ".join(sorted(tokens[i : i + size])) for i in range(len(tokens) - size + 1)}


@dataclass(frozen=True)
class ErasedNames:
    """The suppression list, loaded once per import run (it is tiny)."""

    rows: tuple[tuple[str, str, int, date], ...]  # salt, hash, token_count, erased_on

    @classmethod
    def load(cls, db: Session) -> "ErasedNames":
        found = db.execute(
            select(
                ErasedName.salt, ErasedName.name_hash, ErasedName.token_count, ErasedName.erased_on
            )
        )
        return cls(tuple((s, h, n, d) for s, h, n, d in found))

    def _hit(self, keys_for, on: date | None) -> bool:
        return any(
            (on is None or on <= erased_on)
            and any(_digest(salt, k) == name_hash for k in keys_for(count))
            for salt, name_hash, count, erased_on in self.rows
        )

    def matches(self, name: str | None, on: date | None) -> bool:
        """A field that IS a name (Booksy's client column). `on` is the record's own
        date; with no date we err on the side of privacy."""
        key = name_key(name)
        return bool(key) and self._hit(lambda _count: (key,), on)

    def mentions(self, text: str | None, on: date | None) -> bool:
        """A hand-typed field that may carry extra words (a voucher's cell). Same
        rule the erase-time scrub uses, so scrub and re-import can not disagree."""
        return self._hit(lambda count: _freetext_names(text, count), on)


def anonymous_client(db: Session) -> Client:
    """The one shared placeholder that anonymised visits hang off."""
    anon = db.scalars(
        select(Client).where(Client.is_anonymous.is_(True)).order_by(Client.id)
    ).first()
    if anon is None:
        anon = Client(first_name=ANON_FIRST, last_name=ANON_LAST, is_anonymous=True)
        db.add(anon)
        db.flush()
    return anon


def anonymous_client_id(db: Session) -> int | None:
    return db.scalars(
        select(Client.id).where(Client.is_anonymous.is_(True)).order_by(Client.id)
    ).first()


def ensure_real_client(client: Client) -> None:
    """Nothing new may be attached to the placeholder: it belongs to no erasable
    person, is shown next to every other erased client's history, and a note on an
    anonymised visit ("to była Anna K.") would re-identify it."""
    if client.is_anonymous:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="to jest anonimowy profil RODO — nie można go zmieniać"
        )


def _has_live_namesake(db: Session, key: str, except_id: int) -> bool:
    others = db.execute(
        select(Client.first_name, Client.last_name).where(
            Client.id != except_id, Client.is_anonymous.is_(False)
        )
    )
    return any(name_key(first, last) == key for first, last in others)


@dataclass(frozen=True)
class Anonymised:
    visits: int
    name_suppressed: bool  # False when a live namesake made name-level handling unsafe


def anonymise_client(db: Session, client: Client, today: date) -> Anonymised:
    """Everything described in the module docstring, for one client. The caller
    deletes the client row afterwards."""
    key = name_key(client.first_name, client.last_name)
    by_name = bool(key) and not _has_live_namesake(db, key, client.id)
    anon = anonymous_client(db)

    moved = db.execute(
        update(Visit).where(Visit.client_id == client.id).values(client_id=anon.id, notes=None)
    ).rowcount

    # Spellings to remember: her row's name plus however Booksy spelled her on the
    # packages LINKED to her (staff may have corrected "Ania" to "Anna" on our side).
    her_packages = db.scalars(select(Package).where(Package.client_id == client.id)).all()
    spellings = {key} | {name_key(p.client_name) for p in her_packages}
    spellings.discard("")

    for txn in db.scalars(select(RegisterTxn).where(RegisterTxn.client_name.is_not(None))):
        if name_key(txn.client_name) in spellings:
            txn.client_name = None  # always — see "LIVE NAMESAKE WINS"

    her_package_ids = {p.id for p in her_packages}
    for pkg in db.scalars(select(Package)):
        linked = pkg.id in her_package_ids
        if linked or (by_name and pkg.client_id is None and name_key(pkg.client_name) == key):
            pkg.client_name = ANON_NAME
    for red in db.scalars(select(PackageRedemption)):
        linked = red.package_id in her_package_ids
        if linked or (by_name and name_key(red.client_name) == key):
            red.client_name = ANON_NAME
    if by_name:
        size = len(key.split())
        for voucher in db.scalars(select(Voucher)):  # typed by hand, may carry extra words
            if key in _freetext_names(voucher.client_name, size):
                voucher.client_name = ANON_NAME
        for spelling in spellings:
            salt = secrets.token_hex(16)
            db.add(
                ErasedName(
                    salt=salt,
                    name_hash=_digest(salt, spelling),
                    token_count=len(spelling.split()),
                    erased_on=today,
                )
            )
    db.flush()
    return Anonymised(visits=moved, name_suppressed=by_name)
