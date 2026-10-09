# Computations

Numbers should not be fished out of a document: the slide they live on may be stale, and a model can misread a table. The Computations tab (also called Data) lets a project answer numeric questions exactly, from your own tables, with a receipt.

Tables and computations do nothing until the **Compute** stage is set to *Attested computations* (see [Use it in answers](#use-it-in-answers)).

## The idea

You define *computations*: a parameterised, read-only SQL query over your data tables, plus checks the result must pass. At question time the model may only **pick** a computation and **fill in its parameters**; it can never write the query. The query runs on a read-only connection with a time limit, the result is checked, and the answer is rendered from the result without a model rewriting the number. A **receipt** (the SQL, the parameters, the result and the checks) goes with the answer.

## Add data tables

1. Open the **Computations** tab and upload a CSV, for example sales by region and quarter. Up to 50 MB and 200,000 rows per table.
2. The table appears with its columns. Delete a table to remove it.

## Define a computation

For each figure people ask for ("quarterly revenue for a region", "active users last month"), add a computation:

| Field | Meaning |
| --- | --- |
| Name | A short identifier (lower case letters, digits and underscores) |
| Description | What it computes, in words; the router reads this to decide when to use it |
| Parameters | Typed values the question supplies (name, type, optionally the allowed values) |
| SQL | One read-only `SELECT` (or `WITH ... SELECT`) using `:parameter` placeholders |
| Unit | Shown after a single value, for example USD |

### Attestation

Every computation has declarative checks that the result must pass before anyone sees it:

- **Min rows** and **Max rows**,
- required **Columns**, in order,
- **No empty values**,
- numeric **bounds** per column.

Saving a computation prepares its query against your data so a typo fails now and not when someone asks. Attesters are declarative on purpose: code that arrives with a project is never executed.

## Use it in answers

Set the **Compute** stage to *Attested computations* in [Configure](/docs/configure). Before retrieving, the Generate model checks whether a computation answers the question and fills in its parameters. If it does, the answer comes straight from the result, with its receipt. If a check fails, the **If the result fails attestation** option decides: answer from the documents instead with a warning that their numbers may be out of date, or refuse.

The tab marks computations that have not been used in answers yet.
