The same information from [upgrading from 3.x](upgrade-3x.md) apply, except that there are conflicting database migrations (the Aleph 4 version introduced database migrations that OpenAleph 5 doesn't contain as it was forked off of the 3.x series.)

To fix this, the `alembic_version` table value needs to manually set to the migration version `c52a1f469ac7`, which is the last migration version _Aleph_ and _OpenAleph_ have in common:

```psql
UPDATE alembic_version SET version_num = 'c52a1f469ac7';
```

Then, follow the [upgrade from 3.x steps](upgrade-3x.md).

Please reach out to us in our [community discourse](https://darc.social) or via [hi@dataresearchcenter.org](mailto:hi@dataresearchcenter.org) to get specific guidance on how to upgrade from the 4.x versions to the current OpenAleph version if you run into trouble.
