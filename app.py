create table matieres_enseignant (
  id uuid primary key default gen_random_uuid(),
  teacher_id integer references users(id),
  matiere text not null,
  niveau_classe text,
  etablissement text,
  nb_semaines int default 32,
  programme_officiel_url text,
  programme_texte_extrait text,
  created_at timestamp default now()
);

alter table progressions add column if not exists matiere_id uuid references matieres_enseignant(id);

alter table matieres_enseignant disable row level security;
