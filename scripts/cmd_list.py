"""F-24 fix: `--list` subcommand ka apna module.

main.py ke god-CLI ko dheere-dheere subcommand modules me todna hai;
--list pehle (saara behavior as-is: DB order, id print, empty-id skip nahi).
"""

from core.dua_database import DB


def cmd_list() -> None:
    """Sab dua IDs print karo (pehle main.py --list branch ka exact behavior)."""
    for dua in DB.get_all_duas():
        print(dua.get("id", ""))
