"""Cache filename derivation.

This is the function whose earlier, looser version reported Coreograph 2.4.6 as
present when the cache held it under a different URI's name, and Nextflow went to
the network mid-run. The exact strings below are taken from real cache entries and
from a real Nextflow pull message.
"""

from container_manifest import cache_filename


class TestCacheFilename:
    def test_docker_uri_keeps_registry_prefix(self):
        """The bug: mcmicro declares this without `docker.io/`, we declare it with.

        Same image, different cache filename, and Nextflow only looks for one.
        """
        assert (
            cache_filename("docker.io/labsyspharm/unetcoreograph:2.4.6")
            == "docker.io-labsyspharm-unetcoreograph-2.4.6.img"
        )
        assert (
            cache_filename("labsyspharm/unetcoreograph:2.4.6")
            == "labsyspharm-unetcoreograph-2.4.6.img"
        )

    def test_https_scheme_stripped(self):
        assert (
            cache_filename(
                "https://depot.galaxyproject.org/singularity/ashlar:1.19.0--pyhdfd78af_0"
            )
            == "depot.galaxyproject.org-singularity-ashlar-1.19.0--pyhdfd78af_0.img"
        )

    def test_seqera_blob_uri(self):
        sha = "707825bb6afa202806406063665a361b2a4a2fc6d6f802132359407408826ffe"
        got = cache_filename(
            f"https://community-cr-prod.seqera.io/docker/registry/v2/blobs/sha256/70/{sha}/data"
        )
        assert got == (
            f"community-cr-prod.seqera.io-docker-registry-v2-blobs-sha256-70-{sha}-data.img"
        )

    def test_ghcr_uri(self):
        assert (
            cache_filename("ghcr.io/schapirolabor/background_subtraction:v0.5.1")
            == "ghcr.io-schapirolabor-background_subtraction-v0.5.1.img"
        )

    def test_sif_extension_preserved(self):
        assert cache_filename("oras://example.org/tool.sif:1.0").endswith(".sif")
        assert cache_filename("https://example.org/tool.sif") == "example.org-tool.sif"

    def test_no_slashes_left(self):
        """A '/' in the result would mean Nextflow looks in a subdirectory."""
        for uri in (
            "docker.io/a/b:1",
            "https://x.org/y/z/data",
            "quay.io/biocontainers/ashlar:1.19.0--pyhdfd78af_0",
        ):
            assert "/" not in cache_filename(uri)
