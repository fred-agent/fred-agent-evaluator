#!/usr/bin/env python3
"""
Generic script to generate OpenAPI JSON specification for any FastAPI backend
without starting the server.
"""

import json
import os
import sys
from pathlib import Path


def main():
    """Generate OpenAPI JSON specification."""
    try:
        # Determine the backend directory from current working directory
        backend_dir = Path.cwd()
        app_name = '_'.join(sys.argv[1:])
        app_dir = backend_dir / app_name
        config_dir = backend_dir / "config"

        # Validate that we're in a valid backend directory
        if not app_dir.exists() or not (app_dir / "main.py").exists():
            raise FileNotFoundError(f"Could not find main.py in {backend_dir}")

        if not config_dir.exists() or not (config_dir / "configuration.yaml").exists():
            raise FileNotFoundError(f"Could not find config/configuration.yaml in {backend_dir}")

        # Add the app directory to the Python path
        sys.path.insert(0, str(app_dir))

        # Set required environment variables
        os.environ.setdefault("ENV_FILE", str(config_dir / ".env"))
        os.environ.setdefault("CONFIG_FILE", str(config_dir / "configuration.yaml"))

        # Set dummy secrets for static generation (prevents validation errors).
        # create_app() loads the full config but never connects to any backend here,
        # so dummy values satisfy the fail-fast validators (Postgres / Keycloak) that
        # otherwise refuse to start when no .env is present (e.g. CI).
        os.environ.setdefault("FRED_POSTGRES_PASSWORD", "dummy-password-for-static-generation")  # pragma: allowlist secret
        os.environ.setdefault("KEYCLOAK_CLIENT_SECRET", "dummy-secret-for-static-generation")  # pragma: allowlist secret

        # Import and create the FastAPI app
        from main import create_app
        app = create_app()

        # Generate OpenAPI specification
        openapi_spec = app.openapi()

        # Output file in the backend directory
        output_file = backend_dir / "openapi.json"

        # Write to file
        with open(output_file, 'w') as f:
            json.dump(openapi_spec, f, indent=2)
            f.write('\n')

        backend_name = backend_dir.name
        print(f"✅ OpenAPI specification generated for {backend_name}: {output_file}")
        return 0

    except Exception as e:
        print(f"❌ Error generating OpenAPI specification: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
