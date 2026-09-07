# Reference audit

Checked on 6 September 2026 against `bench-automation` at `b399f2b34d3dab0b069519690def07743c4460a4`.

## Restoration rule and outcome

An original entry is eligible for restoration only when a verifiable, actual official BibTeX export is **exactly identical** to that entry. Correct core metadata, equivalent formatting, matching paper PDFs, or a valid alternative publication version do not satisfy this rule. Citation keys, field order, authors, capitalization, punctuation, braces and whitespace are included in the comparison.

**15 restoration candidates were checked. Fourteen candidates have 17 actual raw exports, all different; one candidate could not be verified because its export request was rate-limited. Exact matches: 0. Entries restored: 0.** This result is limited to the listed exports and does not prove which source the original author used.

All 21 bibliography entries remain covered by the audit: 17 are cited and 4 are unused. The active bibliography retains the prior Scholar-derived versions where no exact restoration qualified. Eighteen entries reproduce their captured Scholar exports. ABC retains the Scholar conference version with only its year/key corrected from the official NeurIPS BibTeX; the raw Scholar export remains unchanged in the archive. ARC Prize Foundation and the live-project entry stay as originally retained.

## Exact comparison evidence

- [Official export archive](official-exports.zip): 17 original HTTP response bodies, with their bytes preserved, including leading/trailing whitespace and line endings. The archive is used so those bytes are not reformatted for repository whitespace conventions.
- [Machine-readable comparison](exact-comparison.json): full export URLs, response types, archive member names, byte lengths, source offsets, SHA-256 values and first differences.
- [Scholar export archive](scholar.bib): auxiliary comparison records, not a claim that Scholar is error-free or that each active entry must match it despite an explicitly corrected metadata error.

The baseline slice begins at the entry's `@` and includes its final closing brace and the immediately following LF. Blank separator lines outside the entry are excluded and this boundary is recorded as byte offsets in the JSON. The exported side is the entire raw response. Equality and hashes use these bytes directly: no trimming, newline conversion, key substitution or other normalization. A separate diagnostic checks whether a mismatch is confined to outer whitespace/line endings; none of the obtained comparisons has only such a difference. That diagnostic never qualifies a restoration.

Offsets below are zero-based. Alternative official editions appear on separate rows for the same candidate. Crossref rows are explicitly DOI registration-agency exports, not falsely described as files downloaded from a journal website.

| Original key | Actual official export URL | Original SHA-256 | Export SHA-256 | Result and first difference |
| --- | --- | --- | --- | --- |
| `paglieri2025balrog` | [official export](https://proceedings.iclr.cc/paper_files/paper/1039-/bibtex) | `8db1bd5f3c0fedde90b4985368c825f149f1c4ddf5c8d96f6cd6bd10abefc593` | `b2aa3294f1870d7ec39d24656629cff67e2bbe264890b634186c7347cde45aaf` | Different; byte 15: citation key differs (`paglieri2025balrog` vs `ICLR2025_f0b1515b`). |
| `zhang2025videogamebench` | [official export](https://arxiv.org/bibtex/2505.18134) | `6c3fd7232b77c7a94dfb61eb3f25a20abbca696b92465e5f792886b07efa4ea8` | `71f444b8e8aa5ace609a3e85ee74d22fdecc633faadffd660724fd3ed5f4b49e` | Different; byte 1: entry type differs; key also differs (`zhang2026videogamebenchvisionlanguagemodelscomplete`). |
| `phan2025textquests` | [official export](https://arxiv.org/bibtex/2507.23701) | `3005ae9962ffb90345b6a28f893885c51490d7d027a5b103095a413d1ba572d6` | `f3d2fb304786edfd611cb3303a395e9cd865204473ba6b456758061ac861451b` | Different; byte 1: entry type differs; key also differs (`phan2025textquestsgoodllmstextbased`). |
| `hu2025lmgame` | [official export](https://arxiv.org/bibtex/2505.15146) | `f321ae263f25ebc9609dab2ce221d6f411b3f5f4e89c06bce88ce74c0fcb2d21` | `2cee1e30bba511d76c35991ab369c91fe729db0c8ae8bef67480f625a6db9097` | Different; byte 1: entry type differs; key also differs (`hu2025lmgamebenchgoodllmsplaying`). |
| `hu2025lmgame` | [official export](https://proceedings.iclr.cc/paper_files/paper/8824-/bibtex) | `f321ae263f25ebc9609dab2ce221d6f411b3f5f4e89c06bce88ce74c0fcb2d21` | `439be1fafe9d0960bb35563cce43f65e098a4239fbf9a1561e13ac3d1a1cb3a9` | Different; byte 1: entry type differs; key also differs (`ICLR2026_83a4ea71`). |
| `park2025orak` | [official export](https://arxiv.org/bibtex/2506.03610) | `138029bac02a737ce6b547395adc21370d2dc74d29132772d5530d819ef4dc20` | `e28a2cee5c6e777f59547bae02f2782f83c31d0489da5eaa25ec46b0b4b9c2a9` | Different; byte 1: entry type differs; key also differs (`park2026orakfoundationalbenchmarktraining`). |
| `park2025orak` | [official export](https://proceedings.iclr.cc/paper_files/paper/10572-/bibtex) | `138029bac02a737ce6b547395adc21370d2dc74d29132772d5530d819ef4dc20` | `35d31b1b3adfd6d6fec1b3575fb2e5a6c58adc9641b0221972ecefb961b34ca0` | Different; byte 1: entry type differs; key also differs (`ICLR2026_63506d49`). |
| `gioacchini2024agentquest` | [official export](https://arxiv.org/bibtex/2404.06411) | `94814088e5b1f0b55eb0f55fe2b0ec6e329323766a8d4ddd0425558a68e3529f` | `765be2f7c92875f3965d5a94639e8ff2052d5daf0a42c001b69866a4c01f724e` | Different; byte 1: entry type differs; key also differs (`gioacchini2024agentquestmodularbenchmarkframework`). |
| `hafner2022crafter` | [official export](https://arxiv.org/bibtex/2109.06780) | `3abada5448fd9326af3d5284e51333394c546fb38f21e658d088c3d04a3fae9e` | `314d18f85ca1d1567579f313c7bac5885feb0c3d642f2a8d7cb7d9c91ade4420` | Different; byte 1: entry type differs; key also differs (`hafner2022benchmarkingspectrumagentcapabilities`). |
| `kuttler2020nethack` | [official export](https://proceedings.neurips.cc/paper_files/paper/10367-/bibtex) | `61bf52665771be5f9655915e3329570c9ba41c289d43786a764ab6ad26433933` | `c5798a7b1a15499a3535ba1885803c04c5ded91bee60e696f2b64a548db360f6` | Different; byte 15: citation key differs (`kuttler2020nethack` vs `NEURIPS2020_569ff987`). |
| `zhu2025abc` | [official export](https://arxiv.org/bibtex/2507.02825) | `d269bc8c599e668063f992f5b89ecd7fcfc1c6dc883137f7ee1e2af4dffb9e4d` | `6cfe77635b2db0c4157d4f334010b6824f5d3bb8881936b0f9a3b88fa4d7857e` | Different; byte 1: entry type differs; key also differs (`zhu2025establishingbestpracticesbuilding`). |
| `zhu2025abc` | [official export](https://proceedings.neurips.cc/paper_files/paper/33049-/bibtex) | `d269bc8c599e668063f992f5b89ecd7fcfc1c6dc883137f7ee1e2af4dffb9e4d` | `184eb8db38231fefe5ce375ef9def498c875ce5502d20f547ace3200255e1818` | Different; byte 1: entry type differs; key also differs (`NEURIPS2025_f316275b`). |
| `chiang2024chatbot` | [official export](https://arxiv.org/bibtex/2403.04132) | `cd7496fd49e2941b67d1caa1282d8ddbd7000a1b8b46a21eb070f26c660078d1` | `575c2607770544bcfcf8edc640756f3474fdaa6f339c76ce682981532e7097e3` | Different; byte 1: entry type differs; key also differs (`chiang2024chatbotarenaopenplatform`). |
| `wilson1927probable` | [DOI export, Accept: application/x-bibtex](https://doi.org/10.1080/01621459.1927.10502953) | `6ff597923e4fd04be0638feb59dd2f2d145568667680c1c2f84532d1d58e292e` | `a63a036462031f76193e5c3b32e273e9e9fe16329596c81a7ca85f1b946855cd` | Different; byte 0: original starts with `@`; export starts with a space. Key also differs: `Wilson_1927`. |
| `chollet2019measure` | [official export](https://arxiv.org/bibtex/1911.01547) | `37dc50862bc85d1008368b3ea0895a4a60dd32f3ff03766387724180ee90e39a` | `e9280705de4b908720ba1ca37c79126c35433a21aba96e5203f8d954ca558f2c` | Different; byte 1: entry type differs; key also differs (`chollet2019measureintelligence`). |
| `bellemare2013ale` | [requested DOI export](https://doi.org/10.1613/jair.3912), Accept: application/x-bibtex | `92d86d1a0d2a62c880be32bca4f8c0633b46cc10968f9b26b8c54a7913d81cc1` | Not obtained | **Unverifiable:** HTTP 429. Metadata agreement is not an exact-export match. No restoration. |
| `fan2022minedojo` | [official export](https://proceedings.neurips.cc/paper_files/paper/17813-/bibtex) | `32745abb1725b5dce8810990cb40d3274cd4aa77d07bb68f625d94321b2e03e5` | `f60ce36e89fa73f851ec56429758ae1cfacb86c54dff819f2a5234e3a4ba7974` | Different; byte 1: entry type differs; key also differs (`NEURIPS2022_74a67268`). |
| `xie2024osworld` | [official export](https://proceedings.neurips.cc/paper_files/paper/26355-/bibtex) | `5dd8369a4d5c89efc42c13b728a272810cfde0f3b7bf6a3e754a8c0295f72090` | `bb4d6d3593ba6a32b1c1f9a5c5c7ed1438a1bc18305c13110948a923af6fb56c` | Different; byte 1: entry type differs; key also differs (`NEURIPS2024_5d413e48`). |

The arXiv export endpoints above are the actual `/bibtex/{id}` endpoints used by arXiv's citation interface, not BibTeX assembled from metadata. The ICLR/NeurIPS endpoints are the BibTeX links supplied by the corresponding official proceedings pages. DOI content negotiation follows [Crossref's documented export interface](https://www.crossref.org/documentation/retrieve-metadata/content-negotiation/).

## Full bibliography decisions

Bibliographic correctness and restoration eligibility are separate findings. The assessments below concern the original fields supplied; they do not establish a historical export source.

| Original entry | Used | Metadata assessment from primary records | Final disposition | Primary evidence |
| --- | --- | --- | --- | --- |
| BALROG / paglieri2025balrog | Yes | Correct core fields; name variants are compatible with the official arXiv byline. | No restoration; keep the prior Scholar-derived entry. | [ICLR BibTeX](https://proceedings.iclr.cc/paper_files/paper/1039-/bibtex); [arXiv](https://arxiv.org/abs/2411.13543) |
| VideoGameBench / zhang2025videogamebench | Yes | Correct title, authors, 2025 year and arXiv identifier; capitalization is not an error. | No restoration; keep the prior Scholar-derived entry. | [arXiv](https://arxiv.org/abs/2505.18134) |
| TextQuests / phan2025textquests | Yes | Correct title, authors, year and identifier. | No restoration; keep the prior Scholar-derived entry. | [arXiv](https://arxiv.org/abs/2507.23701) |
| lmgame-Bench / hu2025lmgame | Yes | Correct 2025 preprint; the ICLR 2026 version is also real. | No restoration; keep the prior Scholar-derived entry. Active key: `hu2026lmgame`. | [arXiv](https://arxiv.org/abs/2505.15146); [ICLR BibTeX](https://proceedings.iclr.cc/paper_files/paper/8824-/bibtex) |
| GVGAI-LLM / nasir2025gvgai | Yes | Incorrect first author: Nasir is a coauthor, not the first author. | Keep the verified first-author correction and the prior Scholar-derived entry. Active key: `li2025gvgai`. | [arXiv](https://arxiv.org/abs/2508.08501) |
| Orak / park2025orak | Yes | Correct 2025 preprint and first-author abbreviation; ICLR 2026 is a later valid version. | No restoration; keep the prior Scholar-derived entry. Active key: `park2026orak`. | [arXiv](https://arxiv.org/abs/2506.03610); [ICLR BibTeX](https://proceedings.iclr.cc/paper_files/paper/10572-/bibtex) |
| ARC-AGI-3 / arc2026arcagi3 | Yes | Correct corporate author ARC Prize Foundation, title, year and identifier. | Keep the original correct corporate author ARC Prize Foundation. This was already retained, not a restoration. | [arXiv](https://arxiv.org/abs/2603.24621) |
| AutumnBench / das2025autumnbench | Yes | Incorrect first-author surname: the official record names Archana Warrier. | Keep the verified first-author correction and the prior Scholar-derived entry. Active key: `warrier2025benchmarking`. | [arXiv](https://arxiv.org/abs/2510.19788) |
| AgentQuest / gioacchini2024agentquest | No | Correct 2024 arXiv preprint; the NAACL publication is another valid record. | No restoration; keep the prior Scholar-derived entry. | [arXiv](https://arxiv.org/abs/2404.06411); [ACL BibTeX](https://aclanthology.org/2024.naacl-demo.19/#citeBibtex) |
| Crafter / hafner2022crafter | Yes | Correct ICLR 2022 citation. The 2021 arXiv date refers to the preprint. | No restoration; keep the prior Scholar-derived entry. Active key: `hafner2021benchmarking`. | [OpenReview paper](https://openreview.net/pdf?id=1W0z96MFEoH); [author page](https://danijar.com/project/crafter/) |
| NetHack / kuttler2020nethack | Yes | Correct NeurIPS 2020 identity, title and authors. Alexander H. is supported by the arXiv record; optional fields and name styling differ. | No restoration; keep the prior Scholar-derived entry. | [NeurIPS BibTeX](https://proceedings.neurips.cc/paper_files/paper/10367-/bibtex); [arXiv](https://arxiv.org/abs/2006.13760) |
| ABC / zhu2025abc | Yes | Correct 2025 preprint title with “for” and its author list. The proceedings title uses “in” and has an updated author list. | No restoration to the old preprint. Keep the Scholar conference entry and correct its year from 2026 to official BibTeX year 2025; key zhu2025establishing. Active key: `zhu2025establishing`. | [arXiv](https://arxiv.org/abs/2507.02825); [NeurIPS BibTeX](https://proceedings.neurips.cc/paper_files/paper/33049-/bibtex) |
| HORIZON / wang2026horizon | Yes | Incorrect given name: the official first author is Xinyu Jessica Wang, not Zora Wang. | Keep the verified first-author correction and the prior Scholar-derived entry. Active key: `wang2026long`. | [arXiv](https://arxiv.org/abs/2604.11978) |
| TextAtari / gan2025textatari | Yes | Incorrect first-author surname Gan and publication year 2506. | Keep the verified first-author correction and the prior Scholar-derived entry. The year is corrected from 2506 to 2025. Active key: `li2025textatari`. | [arXiv](https://arxiv.org/abs/2506.04098) |
| Chatbot Arena / chiang2024chatbot | Yes | Correct 2024 arXiv record, title and full author list. | No restoration; keep the prior Scholar-derived entry. | [arXiv](https://arxiv.org/abs/2403.04132) |
| Wilson / wilson1927probable | Yes | Correct author, title, JASA 22(158), pages 209-212 and year 1927. | No restoration; keep the prior Scholar-derived entry. | [publisher DOI](https://doi.org/10.1080/01621459.1927.10502953); [deposited DOI metadata](https://api.crossref.org/works/10.1080/01621459.1927.10502953); [paper scan](https://jhanley.biostat.mcgill.ca/c607/ch08/wilson_jasa_1927.pdf) |
| On the Measure of Intelligence / chollet2019measure | No | Correct 2019 arXiv title, author and identifier. | No restoration; keep the prior Scholar-derived entry. | [arXiv](https://arxiv.org/abs/1911.01547) |
| ALE / bellemare2013ale | Yes | Correct authors, title, JAIR 47, pages 253-279 and year 2013. | No restoration; export equality could not be verified. Keep the prior Scholar-derived entry. Active key: `bellemare2013arcade`. | [JAIR record](https://www.jair.org/index.php/jair/article/view/10819); [deposited DOI metadata](https://api.crossref.org/works/10.1613/jair.3912) |
| Gemini Plays Pokemon / joelz2025gemini | No | Correct web/live-project identity, author and 2025 provenance, confirmed by the creator. It is not a research paper. | Keep the original misc/web entry; this was already retained, not a restoration. | [creator article](https://blog.jcz.dev/the-making-of-gemini-plays-pokemon); [stream](https://www.twitch.tv/gemini_plays_pokemon) |
| MineDojo / fan2022minedojo | No | Correct NeurIPS 2022 title and complete author list. Its simplified field layout differs from the official inproceedings export. | No restoration; keep the prior Scholar-derived entry. | [NeurIPS BibTeX](https://proceedings.neurips.cc/paper_files/paper/17813-/bibtex) |
| OSWorld / xie2024osworld | Yes | Correct NeurIPS 2024 title, year and first author; and others is an intentional abbreviation. | No restoration; keep the prior Scholar-derived entry. | [NeurIPS BibTeX](https://proceedings.neurips.cc/paper_files/paper/26355-/bibtex) |

## Metadata conflicts and access limits

- **ARC-AGI-3:** the paper names **ARC Prize Foundation**; Scholar omits “Prize”. The existing correct name remains. This is resolved and does not require an entry restoration.
- **ABC:** the [actual NeurIPS BibTeX](https://proceedings.neurips.cc/paper_files/paper/33049-/bibtex) states **2025** even though its webpage publication-date metadata and Scholar export show 2026. Only the year and year-bearing key of the existing Scholar conference entry are corrected. Its conference version, title, author truncation and other fields remain; the original arXiv entry is **not** restored.
- **Versions:** ICLR 2022 Crafter, ICLR 2025 BALROG, NeurIPS NetHack/OSWorld/MineDojo and the original preprints have supporting official records. This semantic agreement is not a byte-for-byte export match. Current arXiv export keys/years may reflect later revisions; the exact captured bytes are reported without modification.
- **OpenReview:** the Crafter forum showed a browser-verification page. No check was bypassed and no forum BibTeX capture is claimed. Its separately available arXiv official export was compared and differs; its PDF/author page is supporting metadata evidence only.
- **Journal exports:** Wilson was obtained through the documented DOI/Crossref export. ALE returned HTTP 429 and has no obtained export hash; the publisher page and DOI metadata do not make it a match.
- **Web source:** the Gemini creator's article confirms the live project. A separately indexed making-of blog is not substituted for the Twitch stream, and no paper-format citation is fabricated.

## Support for manuscript corrections

| Source | Location checked | Scope correction |
| --- | --- | --- |
| BALROG, ICLR 2025 | pp. 3 and 7; NetHack knowledge-probe analysis | Its best tested model reaches 1.5% average NetHack progression, and both language-only and language-vision modes are evaluated. Its knowledge probes do not measure these models' knowledge of Heroes of Jin Yong. |
| ARC-AGI-3 | Abstract; sections 2.2, 2.3.2 and 3.5 | Human solvability is environment-level calibration. The action menu includes five key actions plus undo and coordinate selection, with a subset per environment. The random-policy acceptance threshold is at most 1 in 10,000; a failed single run cannot prove impossibility. |
| lmgame-Bench; TextQuests | lmgame-Bench introduction/methods; TextQuests introduction and Dynamic Thinking | Harnesses affect measured performance. Accepting arbitrary harnesses measures submitted systems and does not remove this confound. Efficiency comparisons are supported without claiming identical budgets. |
| GVGAI-LLM | Section 3.2, p. 4 of arXiv v3 | Meaningful actions use reward or symbolic-state change and exclude cancelling moves in a four-step window. This manuscript's pixel-change and reversal formulas are its own diagnostics. |
| Chatbot Arena | Sections 3-4 and ranking inference | Arena uses pairwise human preferences and uncertainty-aware ranking. Its statistical procedure is not this manuscript's Wilson-overlap display, and its protocol does not establish this manuscript's self-identification policy. |
| VideoGameBench | Abstract; scoring/progress-tracking description and Figure 2 | The 0.48% baseline and perceptual hashing of walkthrough checkpoints are directly supported. |
| AutumnBench; Crafter; Orak; ABC; HORIZON; OSWorld | Introductions and relevant methods; Orak section 3.1; ABC p. 2; OSWorld section 4.1 | Retain supported comparisons while distinguishing this benchmark's protocol and empirical claims from the source papers. |

The prior, source-verified prose corrections remain. No new substantive manuscript rewriting is introduced by the restoration audit; only ABC's year-bearing citation key changes. The benchmark implementation, empirical results, figures, style and anonymization settings are unchanged.

## Validation

- `cd paper/src && latexmk -pdf main.tex`; all 17 in-text citation keys resolve.
- A separate BibTeX run citing `*` parses all 21 entries, including the four unused entries, with unique keys.
- The export ZIP is re-read and every member's SHA-256 is checked against the comparison manifest. All 17 byte comparisons are different and none is just an outer-whitespace/line-ending discrepancy.
- No candidate original entry is restored. Eighteen active entries still match the raw Scholar exports; ABC differs only in year/key, and ARC/the live entry remain unchanged from the base.
- The PDF is rendered and checked for clipping, overlap and unresolved references. Existing CJK/hyperref and natural underfull-box messages are distinguished from citation errors.
- `git diff --check` passes for authored changes; exact export whitespace is preserved inside the ZIP.
