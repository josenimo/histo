# josenimo/histo: Citations

This pipeline has no DOI of its own and should not be cited in place of the tools it wraps. If you
use it, please cite the tools below.

> [!NOTE]
> This file is maintained as modules are added, not retrofitted. Nothing here is marked as planned
> any more: every tool listed runs in the pipeline today.

## Pipelines this project is derived from

Both are MIT licensed. This pipeline would not exist without them.

- [sopa](https://www.nature.com/articles/s41467-024-48981-z) — the entire downstream half is derived
  from [nf-core/sopa](https://github.com/nf-core/sopa), and many modules are vendored from it.

  > Blampey, Q., Mulder, K., Gardet, M. et al. Sopa: a technology-invariant pipeline for analyses of image-based spatial omics. Nat Commun 15, 4981 (2024). https://doi.org/10.1038/s41467-024-48981-z

- [MCMICRO](https://www.nature.com/articles/s41592-021-01308-y) — the preprocessing half is derived
  from [nf-core/mcmicro](https://github.com/nf-core/mcmicro). Also the source of the UNetCoreograph
  TMA dearray tool, which has no separate publication.

  > Schapiro, D., Sokolov, A., Yapp, C. et al. MCMICRO: a scalable, modular image-processing pipeline for multiplexed tissue imaging. Nat Methods 19, 311–315 (2022). https://doi.org/10.1038/s41592-021-01308-y

## Frameworks

- [nf-core](https://pubmed.ncbi.nlm.nih.gov/32055031/) — this is not an nf-core pipeline, but it uses
  the nf-core template, modules and tooling.

  > Ewels PA, Peltzer A, Fillinger S, Patel H, Alneberg J, Wilm A, Garcia MU, Di Tommaso P, Nahnsen S. The nf-core framework for community-curated bioinformatics pipelines. Nat Biotechnol. 2020 Mar;38(3):276-278. doi: 10.1038/s41587-020-0439-x. PubMed PMID: 32055031.

- [Nextflow](https://pubmed.ncbi.nlm.nih.gov/28398311/)

  > Di Tommaso P, Chatzou M, Floden EW, Barja PP, Palumbo E, Notredame C. Nextflow enables reproducible computational workflows. Nat Biotechnol. 2017 Apr 11;35(4):316-319. doi: 10.1038/nbt.3820. PubMed PMID: 28398311.

## Preprocessing tools

- [BaSiC / BaSiCPy](https://www.nature.com/articles/ncomms14836) — illumination correction

  > Peng T, Thorn K, Schroeder T, Wang L, Theis FJ, Marr C, Navab N. A BaSiC tool for background and shading correction of optical microscopy images. Nat Commun 8, 14836 (2017). https://doi.org/10.1038/ncomms14836

- [ASHLAR](https://academic.oup.com/bioinformatics/article/38/19/4613/6668278) — stitching and registration

  > Muhlich JL, Chen YA, Yapp C, Russell D, Santagata S, Sorger PK. Stitching and registering highly multiplexed whole-slide images of tissues and tumors using ASHLAR. Bioinformatics. 2022 Sep 30;38(19):4613-4621. doi: 10.1093/bioinformatics/btac544.

- [background_subtraction](https://github.com/SchapiroLabor/Background_subtraction) — pixel-level
  background subtraction, from the Schapiro Lab

  > No publication found. Cite the repository. TODO verify whether a paper now exists.

## Segmentation, data structures and reporting

- [Cellpose](https://www.nature.com/articles/s41592-020-01018-x) — cell segmentation

  > Stringer C, Wang T, Michaelos M, Pachitariu M. Cellpose: a generalist algorithm for cellular segmentation. Nat Methods 18, 100–106 (2021). https://doi.org/10.1038/s41592-020-01018-x

- [StarDist](https://doi.org/10.1007/978-3-030-00934-2_30) — alternative nucleus segmentation,
  under `use_stardist`

  > Schmidt U, Weigert M, Broaddus C, Myers G. Cell Detection with Star-Convex Polygons. MICCAI 2018, LNCS 11071, 265–273 (2018). https://doi.org/10.1007/978-3-030-00934-2_30

- [SpatialData](https://www.nature.com/articles/s41592-024-02212-x) — the Zarr-backed data
  structure the whole downstream half is built on

  > Marconato L, Palla G, Yamauchi KA, Virshup I, Heidari E, Treis T, Vierdag WM, Toth M, Stockhaus S, Shrestha RB, Rombaut B, Pollaris L, Lehner L, Vöhringer H, Kats I, Saeys Y, Saka SK, Huber W, Gerstung M, Moore J, Theis FJ, Stegle O. SpatialData: an open and universal data framework for spatial omics. Nat Methods 22, 58–62 (2025). https://doi.org/10.1038/s41592-024-02212-x

- [AnnData](https://github.com/scverse/anndata)

  > Virshup I, Rybakov S, Theis FJ, Angerer P, Wolf FA. bioRxiv 2021.12.16.473007; doi: https://doi.org/10.1101/2021.12.16.473007

- [Scanpy](https://github.com/theislab/scanpy). The QC report's clustering is `sc.tl.leiden`.

  > Wolf F, Angerer P, Theis F. SCANPY: large-scale single-cell gene expression data analysis. Genome Biol 19, 15 (2018). doi: https://doi.org/10.1186/s13059-017-1382-0

- [Leiden](https://www.nature.com/articles/s41598-019-41695-z). The community-detection algorithm
  behind the QC report's clusters. The report presents them as a summary of staining rather than
  as cell types, because seed-to-seed agreement on the one slide measured so far peaked at 0.596
  adjusted Rand.

  > Traag VA, Waltman L, van Eck NJ. From Louvain to Leiden: guaranteeing well-connected communities. Sci Rep 9, 5233 (2019). https://doi.org/10.1038/s41598-019-41695-z

- [python-igraph](https://igraph.org/). The Leiden implementation actually called.
  `bin/qc_images.py` passes `flavor="igraph"` to `sc.tl.leiden`, so the clustering runs through
  igraph's own implementation rather than through leidenalg, which is not a sopa dependency.

  > Csardi G, Nepusz T. The igraph software package for complex network research. InterJournal, Complex Systems, 1695 (2006). https://igraph.org

## Software packaging and containerisation

- [Anaconda](https://anaconda.com)

  > Anaconda Software Distribution. Computer software. Vers. 2-2.4.0. Anaconda, Nov. 2016. Web.

- [Bioconda](https://pubmed.ncbi.nlm.nih.gov/29967506/)

  > Grüning B, Dale R, Sjödin A, Chapman BA, Rowe J, Tomkins-Tinch CH, Valieris R, Köster J; Bioconda Team. Bioconda: sustainable and comprehensive software distribution for the life sciences. Nat Methods. 2018 Jul;15(7):475-476. doi: 10.1038/s41592-018-0046-7. PubMed PMID: 29967506.

- [BioContainers](https://pubmed.ncbi.nlm.nih.gov/28379341/)

  > da Veiga Leprevost F, Grüning B, Aflitos SA, Röst HL, Uszkoreit J, Barsnes H, Vaudel M, Moreno P, Gatto L, Weber J, Bai M, Jimenez RC, Sachsenberg T, Pfeuffer J, Alvarez RV, Griss J, Nesvizhskii AI, Perez-Riverol Y. BioContainers: an open-source and community-driven framework for software standardization. Bioinformatics. 2017 Aug 15;33(16):2580-2582. doi: 10.1093/bioinformatics/btx192. PubMed PMID: 28379341; PubMed Central PMCID: PMC5870671.

- [Docker](https://dl.acm.org/doi/10.5555/2600239.2600241)

  > Merkel, D. (2014). Docker: lightweight linux containers for consistent development and deployment. Linux Journal, 2014(239), 2. doi: 10.5555/2600239.2600241.

- [Singularity / Apptainer](https://pubmed.ncbi.nlm.nih.gov/28494014/)

  > Kurtzer GM, Sochat V, Bauer MW. Singularity: Scientific containers for mobility of compute. PLoS One. 2017 May 11;12(5):e0177459. doi: 10.1371/journal.pone.0177459. eCollection 2017. PubMed PMID: 28494014; PubMed Central PMCID: PMC5426675.
