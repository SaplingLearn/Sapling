"""Registry of seed packs, one per major. Order is the admin UI's order."""
from __future__ import annotations

from services.account_seed.packs import biology, business, cs, health, mech_eng, psychology
from services.account_seed.schema import MajorPack

PACKS: dict[str, MajorPack] = {
    p.key: p
    for p in (cs.PACK, business.PACK, biology.PACK, psychology.PACK, health.PACK, mech_eng.PACK)
}
