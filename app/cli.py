import click

from app import db
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