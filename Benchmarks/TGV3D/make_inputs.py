"""Generate a TGV3D input from the checked-in 64^3 reference input."""

import argparse
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("physics", "strong", "capacity", "bitwise"))
    parser.add_argument("n", type=int, help="cells per edge of the cubic grid")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    if args.n < 8 or args.n % 8:
        parser.error("n must be a positive multiple of the blocking factor 8")

    if args.mode == "physics":
        # dt = dx = 64/n; both grids reach physical times 32 and 64.
        max_step = args.n
        stop_time = "64"
        plot_int = args.n // 2
    elif args.mode == "bitwise":
        max_step = 10
        stop_time = "1.e30"
        plot_int = 10
    else:
        max_step = 600 if args.mode == "strong" else 10
        stop_time = "1.e30"
        plot_int = -1

    text = Path(__file__).with_name("inputs_physics_64").read_text()
    changes = {
        "max_step": str(max_step),
        "stop_time": stop_time,
        "amr.n_cell": f"{args.n} {args.n} {args.n}",
        "amr.plot_file": "plt",
        "amr.plot_int": str(plot_int),
        "amr.chk_file": "chk",
    }
    for key, value in changes.items():
        text, count = re.subn(rf"(?m)^{re.escape(key)}\s*=.*$", f"{key} = {value}", text)
        if count != 1:
            raise RuntimeError(f"expected one setting for {key}, found {count}")

    args.output.write_text(text)


if __name__ == "__main__":
    main()
