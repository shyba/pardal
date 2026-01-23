from collections import List
import sys

from pardal_router_mojo import route_problem
from pardal_router_mojo.dsn_dump import dsn_dump, dsn_ir


fn main() raises:
    var argv = List[String]()
    for a in sys.argv():
        argv.append(String(a))

    if len(argv) >= 2 and argv[1] == "dsn-dump":
        if len(argv) < 4:
            print("Usage: pardal-router-mojo dsn-dump <in.dsn> <out.json>")
            return
        dsn_dump(argv[2], argv[3])
        return
    if len(argv) >= 2 and argv[1] == "dsn-ir":
        if len(argv) < 4:
            print("Usage: pardal-router-mojo dsn-ir <in.dsn> <out.json>")
            return
        dsn_ir(argv[2], argv[3])
        return

    if len(argv) < 3:
        print("Usage: pardal-router-mojo <problem.json> <routes.json> [cfg.json]")
        print("       pardal-router-mojo dsn-dump <in.dsn> <out.json>")
        print("       pardal-router-mojo dsn-ir <in.dsn> <out.json>")
        return

    var problem = argv[1]
    var routes = argv[2]
    var cfg = argv[3] if len(argv) >= 4 else ""
    route_problem(problem, routes, cfg)
