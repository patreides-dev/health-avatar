import subprocess
from pathlib import Path

import typer
from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.importers.canonical_csv import import_canonical_csv
from app.models import Person, SourceSystem
from app.services.catalog import seed_development

cli = typer.Typer(help="Health Avatar administration CLI.")
db_cli = typer.Typer(help="Database commands.")
seed_cli = typer.Typer(help="Controlled seed commands.")
import_cli = typer.Typer(help="Import commands.")
cli.add_typer(db_cli, name="db")
cli.add_typer(seed_cli, name="seed")
cli.add_typer(import_cli, name="import")


@db_cli.command("upgrade")
def db_upgrade() -> None:
    """Upgrade the configured database to the latest migration."""
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@seed_cli.command("development")
def seed_development_command() -> None:
    """Load idempotent synthetic development data."""
    with SessionLocal() as session:
        typer.echo(seed_development(session))


@import_cli.command("csv")
def import_csv_command(
    path: Path,
    person_external_reference: str = typer.Option(...),
    source_system: str = typer.Option(...),
) -> None:
    """Import a canonical CSV using the shared importer service."""
    if not path.is_file():
        raise typer.BadParameter("PATH must be a readable file")
    with SessionLocal() as session:
        person = session.scalar(
            select(Person).where(Person.external_reference == person_external_reference)
        )
        source = session.scalar(select(SourceSystem).where(SourceSystem.name == source_system))
        if person is None:
            raise typer.BadParameter("Unknown person external reference")
        if source is None:
            raise typer.BadParameter("Unknown source system")
        batch = import_canonical_csv(
            session,
            content=path.read_bytes(),
            filename=path.name,
            source_system=source,
            subject_person=person,
        )
        typer.echo(
            f"batch={batch.id} status={batch.status} accepted={batch.accepted_rows} "
            f"rejected={batch.rejected_rows}"
        )


@cli.command("validate")
def validate() -> None:
    """Validate configuration and database connectivity."""
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    typer.echo("Configuration and database connection are valid.")


if __name__ == "__main__":
    cli()
