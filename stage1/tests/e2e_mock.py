"""End to end against the local mock: mock server + stage 1 in one process. Takes ~17 s (real-time pacing).
Run:  python tests/e2e_mock.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import utf8  # noqa: F401,E402
import mock_munsit  # noqa: E402
import stage1  # noqa: E402

EXPECTED = [
    "أمس رحت للمستشفى",
    "وقابلت الدكتور",
    "وقال لي إن التحاليل طبيعية",
    "بس لازم أرجع بعد أسبوع",
    "وين المختبر",
    "خذ Panadol حبتين بعد الأكل",
    "وبعدين ارجع لل appointment الجاي",
]


async def main():
    server = await mock_munsit.serve(8766)
    args = stage1.parser().parse_args(["--silence", "17", "--url", "ws://localhost:8766", "--out", str(ROOT / "out" / "e2e")])
    stats = await stage1.run(args)
    server.close()
    await server.wait_closed()

    units = [json.loads(l) for l in (ROOT / "out" / "e2e" / f"{stats['session']}.units.jsonl").open(encoding="utf-8")]
    got = [u["text"] for u in units]
    print("\nexpected vs got")
    for i in range(max(len(EXPECTED), len(got))):
        e = EXPECTED[i] if i < len(EXPECTED) else "—"
        g = got[i] if i < len(got) else "—"
        print(f"  {'ok ' if e == g else 'DIFF'}  {e}   |   {g}")
    assert got == EXPECTED, "units differ"
    assert stats["revisions_after_commit"] == 0, "a misheard interim word got committed"
    q = [u for u in units if u["is_question"]]
    assert len(q) == 1 and q[0]["text"] == "وين المختبر"
    assert any(t["lang"] == "en" for u in units for t in u["tokens"])
    assert [u["unit_id"] for u in units] == list(range(1, len(units) + 1))
    print("\nE2E PASSED")


if __name__ == "__main__":
    asyncio.run(main())
