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
  (returnerer bare brukerens egne spor). YouTube, Studio og andre LTI kan ikke kontrolleres via API.

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
  `master_course_restrictions`, `is_master_course_master_content`.

## HTML som Canvas beholder (sanering ved lagring)

* Fjernes: `style`, `script`, `svg`, `noscript`, kommentarer, ukjente elementer; `rel` på lenker.
* Tillatte CSS-egenskaper i `style`: bl.a. `display`, `flex*`, `grid*`, `gap`, `margin*`, `padding*`, `width`,
  `max-width`, `min-width`, `background*`, `border*`, `border-radius`, `color`, `font-size`, `font-family`,
  `font-style`, `line-height`, `text-align`, `text-decoration`, `list-style*`. **Ikke tillatt:** `font-weight`
  (bruk `<strong>`), `box-shadow`, `opacity`, `transform`, `letter-spacing`, `text-transform`, `outline`.
* Lenker til samme Canvas-vert lagres som relative og leses som absolutte med `data-api-*`-attributter –
  normaliser HTML før sammenligning.
