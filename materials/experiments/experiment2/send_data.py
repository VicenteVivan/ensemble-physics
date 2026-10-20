"""Persistence boundary shared by the experiment flow.

Local JSONL is the default.  Set PERSISTENCE_BACKEND=mongodb or both and provide
the documented environment variables to enable remote insertion.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus


APP_ROOT = Path(__file__).resolve().parent


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def _append_jsonl(document):
    configured = Path(os.environ.get("KESAR_DATA_FILE", "results/responses.jsonl"))
    path = configured if configured.is_absolute() else APP_ROOT / configured
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:
        fcntl = None

    with path.open("a", encoding="utf-8") as handle:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(document, ensure_ascii=False, default=_json_default) + "\n")
        handle.flush()
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_UN)
    try:
        display_path = str(path.relative_to(APP_ROOT))
    except ValueError:
        display_path = str(path)
    return {"ok": True, "path": display_path, "written_at_utc": now_utc()}


def _env(primary, legacy):
    return os.environ.get(primary) or os.environ.get(legacy, "")


def _insert_mongodb(document):
    settings = {
        "user": _env("MONGODB_USER", "mdb_user"),
        "password": _env("MONGODB_PASSWORD", "mdb_password"),
        "cluster": _env("MONGODB_CLUSTER_URL", "mdb_cluster_url"),
        "database": _env("MONGODB_DATABASE", "mdb_database_name"),
        "collection": _env("MONGODB_COLLECTION", "mdb_collection_name"),
    }
    missing = [key for key, value in settings.items() if not value]
    if missing:
        return {"ok": False, "skipped": True, "reason": "missing_mongodb_environment", "missing": missing}

    try:
        from pymongo import MongoClient
    except ImportError as exc:
        return {"ok": False, "skipped": True, "reason": "pymongo_not_installed", "error": str(exc)}

    cluster = settings["cluster"]
    if cluster.startswith("mongodb://") or cluster.startswith("mongodb+srv://"):
        uri = cluster
    else:
        uri = (
            f"mongodb+srv://{quote_plus(settings['user'])}:{quote_plus(settings['password'])}"
            f"@{cluster}/?retryWrites=true&w=majority"
        )

    client = None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        payload = deepcopy(document)
        payload["_inserted_at_utc"] = now_utc()
        result = client[settings["database"]][settings["collection"]].insert_one(payload)
        return {"ok": True, "inserted_id": str(result.inserted_id), "written_at_utc": now_utc()}
    except Exception as exc:
        return {"ok": False, "skipped": False, "reason": "mongodb_insert_failed", "error": str(exc)}
    finally:
        if client is not None:
            client.close()


def persist_data(document):
    backend = os.environ.get("PERSISTENCE_BACKEND", "local").strip().lower()
    if backend not in {"local", "mongodb", "both", "none"}:
        raise ValueError("PERSISTENCE_BACKEND must be local, mongodb, both, or none")

    result = {"backend": backend}
    if backend in {"local", "both"}:
        result["local"] = _append_jsonl(document)
    if backend in {"mongodb", "both"}:
        result["mongodb"] = _insert_mongodb(document)
    if backend == "none":
        result["skipped"] = True
        result["reason"] = "persistence_disabled"
    result["ok"] = all(
        value.get("ok", False)
        for value in result.values()
        if isinstance(value, dict)
    ) if backend != "none" else False
    return result
