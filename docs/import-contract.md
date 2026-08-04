# Canonical CSV import contract

The UTF-8 CSV header must exactly be:

```csv
person_external_reference,observation_type,observed_at,value,unit,measurement_method,reliability_classification,source_record_identifier
```

Each data row requires an existing person external reference and observation-type code, an ISO 8601
timestamp with explicit UTC offset, a decimal numeric value, and the observation type's exact unit.
No unit conversion or identity guessing occurs. Measurement methods are `measured`, `estimated`,
`self_reported`, `imported`, `calculated`, or `inferred`; reliability values are `clinical`,
`consumer_device`, `self_reported`, `derived`, or `unknown`.

The importer hashes the exact source bytes with SHA-256. Re-running the same file for the same source
and explicit subject returns the existing batch without inserting rows. Within different files, an
observation is considered a duplicate when source system, non-null source record identifier, person,
and observation type match. This initial strategy depends on stable upstream IDs: it cannot detect
duplicates when IDs change, and it may suppress legitimate corrections or repeated events that reuse
an ID. Future importers should add source-native revision semantics.

Rows validate independently. Accepted rows commit as normalized observations. Rejected rows become
`ImportError` records with their original row, row number, stable code, and message. Accepted rows
also retain the exact source fields in protected JSONB while exposing only normalized values through
the API. A clean batch is
`completed`; mixed/all-rejected batches are `completed_with_errors`; malformed headers/encoding fail
the batch request. Batch counters always describe parsed data rows.
