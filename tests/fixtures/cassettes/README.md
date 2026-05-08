# Cassettes (committed, redacted)

VCR.py YAML cassettes captured from real tenants and redacted via
`tests/captures/_redact.py`. Each cassette is a faithful recording of one
scenario — replayed during tests via `@pytest.mark.vcr`.

**Never commit a file under `.raw/` here.** That subdir is gitignored and
holds intermediate unredacted captures during the recording workflow. Once
redacted, the output goes one directory up.
