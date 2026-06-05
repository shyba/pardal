from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

from pardal.checks import api as check_api
from pardal.checks.api import DuplicateCheckIdError, registered_checks, set_check_package
from pardal.packages.exports import ExportDefinition
from pardal.packages.index import PackageIndex
from pardal.packages.lock import package_content_hash
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.manifest import load_project_manifest


_LOADED_MODULES: set[str] = set()


def load_package_check_modules(package_index: PackageIndex) -> tuple[str, ...]:
    loaded: list[str] = []
    for export in sorted(package_index.checks_by_id.values(), key=lambda item: item.id):
        module_name = _module_name(export.package_id, export.path.as_posix(), export.hash)
        if module_name in _LOADED_MODULES:
            loaded.append(export.id)
            continue
        _check_package_python_trust(export)
        _check_package_python_import_boundaries(export.package_root)
        before = set(registered_checks())
        registry_snapshot = dict(check_api._REGISTERED)
        source_hash_before = package_content_hash(export.package_root)
        spec = importlib.util.spec_from_file_location(module_name, export.absolute_path)
        if spec is None or spec.loader is None:
            raise ProjectConfigError(
                "package.check_import_failed",
                "could not create import spec for check module",
                path=export.absolute_path,
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        package_root_text = str(export.package_root)
        inserted_package_root = False
        old_dont_write_bytecode = sys.dont_write_bytecode
        local_module_names = _package_local_module_names(export.package_root)
        saved_modules = {
            name: sys.modules.pop(name)
            for name in _matching_package_local_module_names(local_module_names)
        }
        try:
            sys.dont_write_bytecode = True
            if package_root_text not in sys.path:
                sys.path.insert(0, package_root_text)
                inserted_package_root = True
            spec.loader.exec_module(module)
        except DuplicateCheckIdError as exc:
            check_api._REGISTERED.clear()
            check_api._REGISTERED.update(registry_snapshot)
            sys.modules.pop(module_name, None)
            raise ProjectConfigError(
                "package.check_duplicate",
                f"duplicate check id {exc.check_id!r}",
                path=export.absolute_path,
            ) from exc
        except Exception as exc:  # pragma: no cover - message carries user module error
            check_api._REGISTERED.clear()
            check_api._REGISTERED.update(registry_snapshot)
            sys.modules.pop(module_name, None)
            raise ProjectConfigError(
                "package.check_import_failed",
                f"check module import failed: {exc}",
                path=export.absolute_path,
            ) from exc
        finally:
            _remove_loaded_package_modules(export.package_root)
            sys.modules.update(saved_modules)
            sys.dont_write_bytecode = old_dont_write_bytecode
            if inserted_package_root:
                try:
                    sys.path.remove(package_root_text)
                except ValueError:  # pragma: no cover - defensive against user import side effects
                    pass
        source_hash_after = package_content_hash(export.package_root)
        if source_hash_after != source_hash_before:
            check_api._REGISTERED.clear()
            check_api._REGISTERED.update(registry_snapshot)
            sys.modules.pop(module_name, None)
            raise ProjectConfigError(
                "package.source_mutated",
                "package check loading must not mutate installed package source files",
                path=export.absolute_path,
                field="package",
            )
        _LOADED_MODULES.add(module_name)
        for check_id in sorted(set(registered_checks()) - before):
            set_check_package(check_id, export.package_id)
        loaded.append(export.id)
    return tuple(loaded)


def _check_package_python_trust(export: ExportDefinition) -> None:
    manifest = load_project_manifest(export.package_root / "pardal.yaml")
    trust = manifest.raw.get("trust")
    if not isinstance(trust, dict) or trust.get("python_checks") is not True:
        raise ProjectConfigError(
            "package.python_checks_untrusted",
            "packages exporting Python checks must declare trust.python_checks: true",
            path=manifest.path,
            field="trust.python_checks",
        )


def _module_name(package_id: str, export_path: str, export_hash: str) -> str:
    raw = f"{package_id}_{export_path}_{export_hash}"
    safe = re.sub(r"[^0-9A-Za-z_]", "_", raw)
    return f"_pardal_package_check_{safe}"


def _package_local_module_names(package_root: Path) -> set[str]:
    names = {path.stem for path in package_root.glob("*.py") if path.name != "__init__.py"}
    names.update(
        path.name
        for path in package_root.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )
    return names


def _matching_package_local_module_names(local_module_names: set[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in sys.modules
            if any(name == local or name.startswith(f"{local}.") for local in local_module_names)
        )
    )


def _remove_loaded_package_modules(package_root: Path) -> None:
    for name, module in list(sys.modules.items()):
        loaded_file = getattr(module, "__file__", None)
        if loaded_file is not None and _is_path_inside(Path(loaded_file), package_root):
            sys.modules.pop(name, None)


def _check_package_python_import_boundaries(package_root: Path) -> None:
    for path in _iter_package_python_files(package_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            raise ProjectConfigError(
                "package.check_import_failed",
                f"check module parse failed: {exc.msg}",
                path=path,
                field=f"line {exc.lineno}",
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_internal_pardal_import(alias.name):
                        raise ProjectConfigError(
                            "package.check_internal_import",
                            "package check modules must import public APIs from pardal.*, not pardal.*",
                            path=path,
                            field=f"line {node.lineno}",
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None and _is_internal_pardal_import(node.module):
                    raise ProjectConfigError(
                        "package.check_internal_import",
                        "package check modules must import public APIs from pardal.*, not pardal.*",
                        path=path,
                        field=f"line {node.lineno}",
                    )


def _iter_package_python_files(package_root: Path) -> tuple[Path, ...]:
    ignored_dirs = {".pardal", "dist", "build", "__pycache__"}
    paths = []
    for path in package_root.rglob("*.py"):
        if set(path.relative_to(package_root).parts) & ignored_dirs:
            continue
        paths.append(path)
    return tuple(sorted(paths))


def _is_internal_pardal_import(module: str) -> bool:
    if module == "pardal.checks":
        return False
    return module == "pardal" or module.startswith("pardal.")


def _is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
