create table tvmovie_gold.bridge_title_genre (
	genre text null,
	genres text null,
	insert_dt timestamptz null
);

create table tvmovie_gold.dim_genre (
	genre text null,
	insert_dt timestamptz null
);

create table tvmovie_gold.dim_title (
	tconst text null,
	title_type text null,
	primary_title text null,
	original_title text null,
	season_number int4 null,
	episode_number int4 null,
	parent_tconst text null,
	parent_title_type text null,
	parent_primary_title text null,
	parent_original_title text null,
	parent_start_year int4 null,
	parent_end_year int4 null,
	insert_dt timestamptz null
);

create table tvmovie_gold.dim_year (
	"year" int4 null,
	insert_dt timestamptz null
);


create table tvmovie_gold.fact_title_rating (
	tconst text null,
	genres text null,
	average_rating numeric(4, 2) null,
	num_votes int4 null,
	runtime_minutes int4 null,
	start_year int4 null,
	end_year int4 null,
	insert_dt timestamptz null
);
