import nox  # type: ignore[import-not-found]


@nox.session(python=False)
def tests(session):
    session.install("pytest")
    session.run("pytest")
