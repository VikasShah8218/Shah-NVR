"""Write the OpenAPI schemas of both services to nvr_client/openapi/ (no server needed).

    py tools/export_openapi.py     then     cd nvr_client && npm run gen:api
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "nvr_client" / "openapi"
SNIPPET = "import json, main; print(json.dumps(main.app.openapi()))"

OUT.mkdir(parents=True, exist_ok=True)
for service, name in (("central_manager", "central"), ("media_node", "node")):
    # Separate interpreter per service: both use the same top-level package names (app, settings...).
    env = {**os.environ, "DATA_DIR": str(Path(os.environ.get("TEMP", "/tmp")) / "nvr_openapi_tmp")}
    result = subprocess.run([sys.executable, "-c", SNIPPET], cwd=ROOT / service, env=env,
                            capture_output=True, text=True, check=True)
    schema = json.loads(result.stdout.strip().splitlines()[-1])
    (OUT / f"{name}.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"{name}: {len(schema['paths'])} paths -> {OUT / f'{name}.json'}")
