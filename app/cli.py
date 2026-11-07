import click

from app.extensions import db
from app.models import User
from app.utils.security import hash_password


def register_cli(app):
    @app.cli.command('create-admin')
    @click.argument('username')
    @click.password_option()
    def create_admin(username, password):
        """Create an admin user: flask --app run create-admin <username>"""
        if User.query.filter_by(username=username).first():
            raise click.ClickException(f"User '{username}' already exists")

        db.session.add(User(
            username=username,
            password_hash=hash_password(password),
            role='admin',
        ))
        db.session.commit()
        click.echo(f"Admin '{username}' created")

    @app.cli.command('replay-draw')
    @click.argument('draw_id', type=int)
    def replay_draw(draw_id):
        """Re-run a draw from its locked entry list and seed and check every recorded winner."""
        from app.services.draw_service import DrawError, replay_draw as replay

        try:
            r = replay(draw_id)
        except DrawError as e:
            raise click.ClickException(str(e))

        click.echo(f"Entry list fingerprint (recorded): {r['fingerprint_recorded']}")
        click.echo(f"Entry list fingerprint (now):      {r['fingerprint_now']}")
        click.echo(f"Seed ({r['seed_source']}): {r['seed']}  [{r['seed_reference']}]")
        ok = r['fingerprint_ok']
        if not ok:
            click.secho("MISMATCH: the entry list has changed since it was locked", fg='red')
        for position, expected, recorded, match in r['picks']:
            ok = ok and match
            mark = click.style('OK', fg='green') if match else click.style('MISMATCH', fg='red')
            click.echo(f"  Winner {position}: expected entry {expected}, recorded entry {recorded}  {mark}")
        if not r['picks']:
            click.echo("  (no winners drawn yet)")
        if ok:
            click.secho("Replay matches the recorded draw.", fg='green')
        else:
            raise click.ClickException("Replay does NOT match the recorded draw")