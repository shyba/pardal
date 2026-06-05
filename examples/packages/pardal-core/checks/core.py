from pardal.checks import Finding, Severity, Stage, check


@check(
    id="pardal.core.fixture",
    stage=Stage.MANIFEST,
    default_severity=Severity.INFO,
)
def fixture_check(ctx):
    return []
