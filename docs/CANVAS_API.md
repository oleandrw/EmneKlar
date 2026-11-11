# Canvas REST API – verifisert referanse for EmneKlar

*Kontrollert mot offisiell dokumentasjon 6. oktober 2026 (developerdocs.instructure.com/services/canvas, som
erstatter canvas.instructure.com/doc/api) og canvas-lms-kildekoden (offentlig speil per 30.4.2026). Verdier her
er brukt direkte i koden – ikke gjett nye verdier; kontroller mot dokumentasjonen.*

## Transport

* `Authorization: Bearer <token>`; **`User-Agent` er påkrevd** (403 uten, fra 20.6.2026); GET med body gir 403.
* `Accept: application/json+canvas-string-ids` (id-er som strenger). POST/PUT med JSON-body.
* Paginering via `Link`-header (`rel="next"`), `per_page` maks 100. URL-ene er opake.
* Struping: 429 (hosted Canvas siden 2025-10-08) eller 403 med «Rate Limit Exceeded» (åpen kildekode).
  Ingen `Retry-After`. `X-Request-Cost` og `X-Rate-Limit-Remaining` på hvert svar. EmneKlar bruker begrenset
  samtidighet (standard 3), eksponentiell tilbaketrekking med jitter, og bremser når bøtta er lav.
* Personlige tilgangstokener: Instructures API-policy sier at apper som brukes av mange, skal bruke OAuth2.
  EmneKlar v1 bruker hver lærers eget token lokalt; OAuth2 via institusjonens utviklernøkkel er en mulig utvidelse.

## Emner og tilganger

* `GET /api/v1/courses` (`enrollment_type`, `enrollment_state`, `state[]`, `include[]=term`).
  `default_view`: `feed | wiki | modules | assignments | syllabus`. `blueprint` finnes på emneobjektet.
* `GET /api/v1/courses/:id/permissions?permissions[]=…` – granulære nøkler: `manage_wiki_create|update|delete`,
  `manage_course_content_add|edit|delete`, `manage_assignments_add|edit|delete`, `manage_files_*`, og avledede
  rettigheter `manage`, `update`, `read_as_admin`, `update_course_details`. Blueprint-standardrestriksjoner krever
  kontonivå `manage_master_courses`.
* `GET/PUT /api/v1/courses/:id/settings` (nøkler på toppnivå), se `features/canvas_settings`.

## Sider

* `GET …/pages?include[]=body` – body på listekall. Sider med `editor: "block_editor"` har ikke HTML-body
  (`block_editor_attributes`) → kan ikke analyseres/rettes som HTML; vises som manuell kontroll.
* `PUT …/pages/:url_or_id` med `wiki_page[body|title|published|front_page|editing_roles]` (`editing_roles`:
  `teachers, students, members, public`). Body maks 500 KB.
* Revisjoner: `GET …/pages/:id/revisions`, `POST …/pages/:id/revisions/:revision_id` (tilbakestiller bare tittel,
  body og url).
* Forside: `GET/PUT …/front_page`. Velg forside med `wiki_page[front_page]=true` (siden må være publisert);
  `course[default_view]=wiki` krever en forside. Å fjerne forsideflagget nullstiller `default_view=wiki`.

## Moduler

* `GET …/modules?include[]=items&include[]=content_details` – elementer tas bare med når modulen har ≤ 100
  elementer; ellers `GET …/modules/:id/items`.
* Modul: `require_sequential_progress`, `prerequisite_module_ids`, `unlock_at`, `published`. **Publisering av en
  modul publiserer også alle elementene** – EmneKlar endrer aldri modulens publiseringsstatus.
* `requirement_type` (`all | one`) står i dokumentasjonen for «Update a module», men `ContextModulesApiController`
  i canvas-lms (kontrollert 6.10.2026) tillater bare `name`, `unlock_at`, `require_sequential_progress` og
  `publish_final_grade`; `requirement_count` brukes bare når en funksjonsbryter er på. EmneKlar tilbyr derfor ikke å
  endre «alle krav / ett krav», og leser alltid verdier tilbake etter skriving for å oppdage slike stille avvik.
* Elementtyper: `File | Page | Discussion | Assignment | Quiz | SubHeader | ExternalUrl | ExternalTool`.
* Fullføringskrav (skriving): `must_view`, `must_submit`, `must_contribute`, `min_score` (+ `min_score`),
  `must_mark_done`. Gyldighet (håndheves av EmneKlar, serveren håndhever bare delvis):

  | Krav | Elementtyper |
  |---|---|
  | `must_view` | alle unntatt SubHeader |
  | `must_contribute` | Assignment, Discussion, Page |
  | `must_submit`, `min_score` | Assignment, Quiz |
  | `must_mark_done` | Assignment, Page |

* Fjern krav ved å sende tomt objekt (`completion_requirement: {}`); JSON `null` ignoreres.
* Flytt element: `PUT …/modules/:module_id/items/:id` med `module_item[module_id]` (+ `position`).

## Filer og medier

* `GET …/courses/:id/files` (`content-type` med bindestrek, `size`, `url`, `created_at`).
* Nedlasting: send token (verifier fases ut), følg omdirigeringer – token sendes aldri til annen vert.
* Teksting: `GET /api/v1/courses/:id/media_objects` (`media_tracks[]` med `kind`, `workflow_state`, `asr`) og
  `GET /api/v1/media_attachments/:attachment_id/media_tracks`. Teksting regnes som funnet når det finnes et spor
  med `kind` `captions|subtitles` og `workflow_state=ready`. Ikke bruk `media_objects/:id/media_tracks`
  (returnerer bare brukerens egne spor). Studio og andre LTI kan ikke kontrolleres via API.
* **Observert 6.11.2026 (hiof.instructure.com, Blueprint-emne):** medielisten viste `media_tracks: []` for alle 170
  medieobjekter, selv om de fleste var tekstet – sporene ligger på mediefilen. EmneKlar stoler derfor bare på
  medielisten når den *viser* teksting, og leser ellers sporene fra vedlegget: id-en i innbyggingen
  (`/media_attachments_iframe/:id`), eller filen i emnet med `media_entry_id` lik medie-id-en (`GET …/files`).
  Canvas viser egne medier også som `<video class="instructure_inline_media_comment" data-media_comment_id=…>` og
  videofiler som `<video><source class="instructure_video_link" src="/courses/:id/files/:id/download">`.
* **Medietype** (kontrollert mot canvas-lms-kildekoden 6. november 2026: `app/models/media_object.rb`,
  `packages/canvas-rce/src/rce/contentRendering.jsx`, `packages/canvas-rce/src/rce/plugins/shared/ContentSelection.js`,
  `lib/data_fixup/add_media_data_attribute_to_iframes.rb`): `media_objects[].media_type` er `audio`/`video`, eller
  normalisert med skråstrek (`audio/*`, `video/mp4`). Bare delen før `/` brukes. Filer har `content-type`. Editoren
  skriver `data-media-type="audio|video"` og `data-media-id` på innbyggingen (`<iframe … src="/media_attachments_iframe/:id?type=audio">`).
  Datarettingsjobben setter `data-media-type="video"` når typen er ukjent, så metadata fra Canvas går foran merkingen.
* YouTube: teksting kontrolleres med `youtube-transcript-api` (uoffisielt, sender bare video-id-en): `is_generated`
  skiller opplasterens teksting fra automatisk teksting.

## Emne-RAG (lesing)

*Kontrollert mot canvas-lms-kildekoden 3. november 2026 (`media_tracks_controller.rb`, `lib/api/v1/media_object.rb`,
`lib/api/v1/discussion_topics.rb`, `courses_controller.rb`).*

* Lærere i emnet: `GET /api/v1/courses/:id/users?enrollment_type[]=teacher&enrollment_type[]=ta&enrollment_type[]=designer`
  (`enrollment_type[]`: `teacher | student | student_view | ta | observer | designer`). Emne-RAG bruker bare `id`.
* Diskusjonstema: `author` (`user_display_json`, `null` når temaet er anonymt) og `user_name`. Svar
  (`…/entries`, `…/view`) hentes aldri.
* Filer: `GET …/files?include[]=user` gir opplasteren (`user.id`).
* Teksting for opplastede mediefiler: `GET /api/v1/media_attachments/:attachment_id/media_tracks?include[]=webvtt_content`
  (`include[]`: `content | webvtt_content | updated_at | created_at`; standard er bare `id, locale, kind,
  media_object_id, user_id`). Gir alle spor for vedlegget, også originalene.
* Medieobjekter: `GET /api/v1/courses/:id/media_objects` gir `media_tracks[]` med `url`
  (`/media_objects/:media_id/media_tracks/:id`, ikke-API-rute som svarer med WebVTT og godtar token) og
  `media_sources[]` (`url`, `content_type`, `bitrate` i kbit/s, `size` i KB, `isOriginal`, `fileExt`) når `sources` ikke
  er utelatt. Varighet finnes ikke i API-et; den anslås som `size × 8 / bitrate` sekunder.
* `GET /api/v1/media_objects/:id/media_tracks` gir bare brukerens egne spor og brukes ikke.

## KI-bildeassistent (filopplasting og bilder i sider)

*Kontrollert mot canvas-lms-kildekoden 4. november 2026 (`doc/api/file_uploads.md`, `lib/api/v1/attachment.rb`,
`app/controllers/files_controller.rb`, `app/controllers/usage_rights_controller.rb`,
`gems/canvas_sanitize/lib/canvas_sanitize/canvas_sanitize.rb`, `app/controllers/wiki_pages_api_controller.rb`,
`packages/canvas-rce/src/common/fileUrl.ts`, `packages/canvas-rce/src/rce/transformContent.ts`).*

* **Opplasting i tre steg:** (1) `POST /api/v1/courses/:id/files` med `name`, `size`, `content_type`,
  `parent_folder_path` (mappen opprettes om den mangler) og `on_duplicate` (`overwrite` er standard, `rename`,
  udokumentert `error`) → `upload_url`, `upload_params` (signatur gyldig i 30 minutter) og eventuelt `file_param`.
  (2) Multipart-POST til `upload_url` **uten** tilgangstoken, med `upload_params` uendret og filen som **siste**
  felt; ingen automatisk omdirigering. (3) 3xx `Location` hentes med token (GET); ved 201 gir `Location` filens
  JSON. EmneKlar bruker `on_duplicate=rename` (overskriver aldri) og filnavn ut fra bildets SHA-256, og gjenbruker en
  fil med samme navn og størrelse (`GET …/files?search_term=`) ved nye forsøk.
* **Bilder i HTML:** `<img src="/courses/:id/files/:file_id/preview" alt=… width=… height=…>` – som Rich Content
  Editor gjør (relativ `/preview`, uten spørring). Ikke bruk filens `url` (inneholder `verifier`). `data-api-endpoint`
  og `data-api-returntype` legges til av Canvas ved lesing og fjernes av editoren – EmneKlar skriver dem ikke.
* **Sanering:** `figure`, `figcaption` og `small` er tillatt; `img` tillater `align alt height src usemap width
  longdesc` (ikke `loading` – det er bare tillatt på `iframe`, så `loading="lazy"` på bilder forventes fjernet ved
  lagring); `src` bare http/https/relativ (ikke `data:`); `data-*` er tillatt; `style` med tillatte CSS-egenskaper
  (`display`, `width`, `max-width`, `height`, `margin`, `font-size`, `text-align` m.fl.). EmneKlar leser siden
  tilbake etter publisering og viser hvilke attributter Canvas fjernet.
* **Synlighet:** en fil som er låst (`locked`, låst mappe eller låsedatoer) vises ikke for studenter. Skjulte filer
  virker via direkte lenke. Krever emnet opphavsrettsinformasjon (`course.usage_rights_required`), blir nye filer
  låst til den er satt: `PUT /api/v1/courses/:id/usage_rights` med `file_ids[]`, `publish=true` og
  `usage_rights[use_justification]` (`own_copyright | used_by_permission | fair_use | public_domain |
  creative_commons`), eventuelt `usage_rights[legal_copyright]`. Læreren velger grunnlaget; EmneKlar velger ikke.
* **Sideoppdatering:** `PUT …/pages/:url` med bare `wiki_page[body]` beholder publiseringsstatus. PUT mot en side som
  ikke finnes, oppretter en ny side – EmneKlar leser alltid siden først (konfliktsjekk).

## Klassiske quizer

* Status: Instructure har **ingen** annonsert sluttdato (vedlikeholdsmodus, april 2026). API-ene fungerer.
* `GET/POST/PUT …/quizzes`, `quiz[…]`: `quiz_type` (`practice_quiz | assignment | graded_survey | survey`),
  `time_limit`, `shuffle_answers`, `hide_results` (`null | always | until_after_last_attempt`),
  `show_correct_answers*`, `allowed_attempts` (−1 = ubegrenset), `scoring_policy` (`keep_highest | keep_latest`),
  `one_question_at_a_time`, `cant_go_back`, `access_code`, `due_at`, `lock_at`, `unlock_at`, `published`.
* **Innstillinger kan forsvinne stille** (f.eks. `scoring_policy` når forsøk ≤ 1) – EmneKlar leser quizen
  tilbake og rapporterer avvik. Send `one_question_at_a_time` sammen med `cant_go_back` (feil i Canvas).
* Spørsmål: lese – svar `{id, text, html, weight}`, **fasit = `weight` 100**; skrive – `answer_text`,
  `answer_html`, `answer_weight`, `answer_comments`. Flervalg uten svar med vekt 100 gjør første svar riktig –
  EmneKlar sender alltid eksplisitt fasit. Send hele spørsmålet ved PUT.
* Grupper: `GET …/quizzes/:id/groups`, `POST …/groups` med `quiz_groups[{name, pick_count, question_points}]`
  («X av Y»). Spørsmål i grupper koblet til spørsmålsbank returneres ikke av spørsmålskallet.
* Upublisert quiz: `points_possible` oppdateres ved neste `PUT …/quizzes/:id` – EmneKlar lagrer quizen på nytt
  etter at spørsmålene er lagt til.

## Blueprint

* Blueprint: `course.blueprint`; `GET …/blueprint_templates/default` (404 hvis ikke blueprint).
  Barneemne: `GET …/blueprint_subscriptions`.
* Lås: `PUT …/blueprint_templates/default/restrict_item` med `content_type` (`assignment | attachment |
  discussion_topic | external_tool | lti-quiz | quiz | wiki_page`), `content_id` (numerisk; sider bruker
  `page_id`), `restricted`, `restrictions[content|points|due_dates|availability_dates]`.
* Låsestatus leses fra listekall (sider, oppgaver, diskusjoner, quizer): `restricted_by_master_course`,
  `master_course_restrictions`, `is_master_course_master_content`, `is_master_course_child_content`.

*Synkronisering og tilknyttede emner – kontrollert mot developerdocs.instructure.com (Blueprint Courses) 6. november
2026:*

* Tilknyttede emner: `GET …/blueprint_templates/default/associated_courses` (liste med Course-objekter).
* Synkroniser: `POST …/blueprint_templates/default/migrations` med `comment`, `send_notification`, `copy_settings`
  (standard `true` for nylig tilknyttede emner), `send_item_notifications`, `publish_after_initial_sync` → BlueprintMigration.
  EmneKlar sender `comment`, `send_notification=false` og `copy_settings=false` (EmneKlar kopierer aldri innstillinger).
* Status: `GET …/migrations/:id`, `workflow_state` `queued | exporting | imports_queued | completed | exports_failed |
  imports_failed` (eksempelet i dokumentasjonen viser også `running`, som behandles som pågående).
* Usynkroniserte endringer: `GET …/unsynced_changes` → ChangeRecord (`asset_id`, `asset_type` `assignment |
  attachment | discussion_topic | external_tool | quiz | wiki_page | syllabus | settings`, `asset_name`,
  `change_type` `created | updated | deleted`, `html_url`, `locked`, `exceptions`). En synkronisering tar med *alle*
  usynkroniserte endringer, også dem som er gjort utenfor EmneKlar – forhåndsvisningen sier det.
* `ExceptionRecord.conflicting_changes`: endringer i det tilknyttede emnets kopi som hindret en Blueprint-endring i å
  bli brukt. Lokale endringer av ulåst innhold blir altså ikke overskrevet ved synkronisering.
* Abonnement: `GET …/blueprint_subscriptions` → `id`, `template_id`, `blueprint_course {id, name, course_code,
  term_name}`.

**Hvordan EmneKlar håndterer Blueprint (ingen egen sperre):**

* Rettinger tilbys også for låst innhold. Canvas avgjør med den tilkoblede brukerens rettigheter. Avviser Canvas
  en endring av låst innhold i et tilknyttet emne (valideringsfeil «… locked by Master Course», HTTP 400 i canvas-lms
  `MasterCourses::Restrictor`), forklarer EmneKlar hvorfor og tilbyr å flytte rettingen til Blueprint-emnet.
* Flytting finner samme innhold i Blueprint-emnet via sideadressen (som synkroniseringen beholder) eller en entydig
  tittel for oppgaver, diskusjoner og quizer, og bruker rettingsoppskriftene på Blueprint-innholdet (lenkene og
  fil-id-ene er ulike i de to emnene; elementet gjenkjennes ved plassering og lenkemål/alt-tekst). Finnes ikke
  innholdet entydig, eller mangler brukeren tilgang til Blueprint-emnet, vises det med forklaring – ingen gjetting.
* Endringer i et Blueprint-emne når de tilknyttede emnene først ved synkronisering; den legges i køen som en egen,
  høyrisiko endring (`blueprint.sync`) og publiseres etter innholdsendringene i samme publisering.
* **Begrensninger:** Canvas-API-et oppgir ikke hvilket objekt i Blueprint-emnet et tilknyttet objekt kommer fra
  (`migration_id` vises ikke i de vanlige innholdskallene), derfor sideadresse/tittel. Nye quizer (New Quizzes) og
  eksterne verktøy kan ikke rettes som HTML. EmneKlar kan ikke vite om en administrator har særrettigheter før Canvas
  svarer.

## Direkte lenker til innhold («Åpne i Canvas»)

* Canvas har ikke API for å peke til et bestemt element i en side. EmneKlar åpner riktig innhold og legger på et
  tekstfragment (`#:~:text=…`, lenketekst eller overskrift) som moderne nettlesere bruker til å rulle til og markere
  teksten; andre nettlesere åpner bare siden.
* Ruter (canvas-lms): `/courses/:id/pages/:url` (+`/edit`), `/assignments/:id` (+`/edit`),
  `/discussion_topics/:id` (+`/edit`, også kunngjøringer), `/quizzes/:id` (+`/edit`), `/assignments/syllabus`,
  `/modules/items/:id`, `/modules#context_module_:id`, `/files?preview=:id`. Objektets `html_url` brukes når Canvas
  oppgir den.

## Emnedesign

*Kontrollert mot canvas-lms-kildekoden 6. november 2026 (`lib/api/v1/assignment.rb`) og prosjektets sanering
(`core/security/sanitize.py`, se under).*

* **Kan formateres** (rik tekst med inline-stil): sider inkl. forsiden og modulintroduksjoner (`wiki_page[body]`),
  oppgavebeskrivelser (`assignment[description]`), emneplanen (`course[syllabus_body]`) og innledningen i klassiske
  quizer (`quiz[description]`). Bare innholdsfeltet sendes – frister, poeng og innstillinger er ikke med i kallet.
* **Utelates:** New Quizzes (`is_quiz_lti_assignment: true` på oppgaven) – instruksjonene ligger i New Quizzes-verktøyet
  med eget API (`/api/quiz/v1/…`), som EmneKlar ikke bruker. Oppgaver som speiler en klassisk quiz
  (`is_quiz_assignment`/`quiz_id`) eller en gradert diskusjon (`discussion_topic`) vises bare som quizen. Quizspørsmål og
  svar, diskusjoner og Canvas' eget grensesnitt (navigasjon, sidetitler, innleveringsknapper, quizkontroller) endres
  ikke.
* Moduler har ikke eget beskrivelsesfelt; «modulintroduksjon» er den første siden i modulen.
* Designet bruker bare tillatte CSS-egenskaper (ikke `box-shadow`, `aspect-ratio`, `font-weight`). Canvas
  re-serialiserer stil (`Arial , sans-serif`, doble anførselstegn, uten mellomrom) – sammenligning normaliserer dette.
  `class` og `data-*` beholdes, men designet gjenkjennes også uten dem.

## HTML som Canvas beholder (sanering ved lagring)

* Fjernes: `style`, `script`, `svg`, `noscript`, kommentarer, ukjente elementer; `rel` på lenker.
* Tillatte CSS-egenskaper i `style`: bl.a. `display`, `flex*`, `grid*`, `gap`, `margin*`, `padding*`, `width`,
  `max-width`, `min-width`, `background*`, `border*`, `border-radius`, `color`, `font-size`, `font-family`,
  `font-style`, `line-height`, `text-align`, `text-decoration`, `list-style*`. **Ikke tillatt:** `font-weight`
  (bruk `<strong>`), `box-shadow`, `opacity`, `transform`, `letter-spacing`, `text-transform`, `outline`.
* Lenker til samme Canvas-vert lagres som relative og leses som absolutte med `data-api-*`-attributter –
  normaliser HTML før sammenligning.
