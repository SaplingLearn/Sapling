alter table public.notes
    add column original_filename text,
    add column original_type text,
    add column original_bytes integer,
    add constraint notes_original_metadata check (
        (original_filename is null and original_type is null and original_bytes is null)
        or (original_filename is not null and original_type is not null and original_bytes is not null
            and original_bytes between 1 and 3000000
            and original_type in ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
    );

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('note-originals', 'note-originals', false, 3000000, array['application/octet-stream'])
on conflict (id) do update set
    public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create index notes_original_owner_idx on public.notes (user_id)
where original_bytes is not null and deleted_at is null;

create function public.check_note_original_quota() returns trigger
language plpgsql set search_path = ''
as $$
declare
    total_bytes bigint;
    owner_bytes bigint;
begin
    if new.original_bytes is null or new.deleted_at is not null then
        return new;
    end if;
    perform pg_catalog.pg_advisory_xact_lock(19317, 1);
    select coalesce(sum(original_bytes), 0),
           coalesce(sum(original_bytes) filter (where user_id = new.user_id), 0)
    into total_bytes, owner_bytes
    from public.notes
    where original_bytes is not null and deleted_at is null and id <> new.id;
    if total_bytes + new.original_bytes > 700000000
       or owner_bytes + new.original_bytes > 10000000 then
        raise sqlstate 'PT413' using message = 'Original file storage quota reached';
    end if;
    return new;
end;
$$;

create trigger notes_check_original_quota
before insert or update of original_bytes, user_id, deleted_at on public.notes
for each row execute function public.check_note_original_quota();
