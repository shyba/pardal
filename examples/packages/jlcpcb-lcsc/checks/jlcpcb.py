from pardal.checks import Severity, Stage, check


@check(
    id="jlcpcb.fixture",
    stage=Stage.ASSEMBLY,
    default_severity=Severity.INFO,
)
def fixture_check(ctx):
    return []
