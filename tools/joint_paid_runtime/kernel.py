"""Joint acceptance process entrypoints, run with the paired Kernel interpreter.

Only product configuration and the external AI adapter are substituted. HTTP
authentication, admission, reservations, execution and finalization are unchanged.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
from pathlib import Path

import uvicorn
import yaml
from alembic import command
from alembic.config import Config
from anytoolai_platform_api.bootstrap import DEFAULT_PRODUCT_BUNDLES
from anytoolai_platform_sdk import ProductBundle

RUN = Path(os.environ["ANY766_RUN_DIR"])
ROOT = Path.cwd()


class LocalProducts(ProductBundle):
    bundle_id = "joint_acceptance"

    def config_roots(self) -> list[Path]:
        return sorted((RUN / "products").iterdir())


def prepare() -> None:
    shutil.copytree(ROOT / "configs/kernel", RUN / "kernel-config")
    products = os.environ["ANYTOOLAI_ENABLED_PRODUCT_IDS"].split(",")
    for bundle in DEFAULT_PRODUCT_BUNDLES:
        for source in bundle.config_roots():
            if source.name not in products:
                continue
            target = RUN / "products" / source.name
            shutil.copytree(source, target)
            path = target / "product.yaml"
            document = yaml.safe_load(path.read_text())
            document["commercial_admission_enabled"] = True
            for metric in document["usage_metrics"]:
                metric["enabled"] = ".test_" not in metric["metric_key"]
            path.write_text(yaml.safe_dump(document, sort_keys=False))


async def worker() -> None:
    from anytoolai_platform_api.bootstrap import build_runtime
    from anytoolai_platform_core.providers.adapters.fake import FakeProviderAdapter
    from anytoolai_platform_core.providers.models import (
        ProviderResponse,
        ResolvedProviderRequest,
    )
    from anytoolai_platform_worker.composition import build_worker

    class ExternalProvider(FakeProviderAdapter):
        async def complete(self, request: ResolvedProviderRequest) -> ProviderResponse:
            if (RUN / "provider-outage").exists():
                raise TimeoutError("Synthetic external provider outage")
            return await super().complete(request)

    runtime = build_runtime(RUN / "kernel-config", bundles=[LocalProducts()])
    instance = build_worker(
        session_factory=runtime.storage.session_factory,
        config_registry=runtime.config_registry,
        provider_adapters={
            "fake": ExternalProvider(
                ROOT / "tests/fixtures/provider/fake_provider_outputs"
            )
        },
        poll_interval_seconds=0.05,
    )
    asyncio.get_running_loop().add_signal_handler(
        signal.SIGTERM, instance.request_shutdown
    )
    try:
        await instance.run_forever()
    finally:
        instance.dispose()


def main() -> None:
    role = sys.argv[1]
    if role == "prepare":
        prepare()
    elif role == "migrate":
        config = Config()
        config.set_main_option("script_location", str(ROOT / "migrations/platform"))
        config.set_main_option(
            "sqlalchemy.url", os.environ["ANYTOOLAI_DATABASE_URL"].replace("%", "%%")
        )
        command.upgrade(config, "head")
    elif role == "api":
        from anytoolai_platform_api.main import create_app

        app = create_app(RUN / "kernel-config", bundles=[LocalProducts()])
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=int(os.environ["ANY766_KERNEL_API_PORT"]),
            access_log=False,
            log_level="warning",
        )
    elif role == "worker":
        asyncio.run(worker())
    else:
        raise ValueError("Unknown joint acceptance role")


if __name__ == "__main__":
    main()
