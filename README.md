# VFB_connectomics_import
A project to produce RDF/OWL representations of connectomics data for import to the VFB integration layer triple store.

## Functional specification

The VFB KB has records for neurons imported from sources that have connectomic data: currently neuprint + multiple CATMAID databases.  These records include the IDs for these neurons used in the sources they are imported from (e.g. bodyIDs from neuprint)  The aim of library is to provide simple, extensible code for importing connectomics assertions about these neurons into the VFB integration layer triple store, via the generation of RDF/OWL. 

Schema for neuron:neuron connectomics:

(i)-[synapsed_to: { weight: n }]->(j)

* In future we may add:
   * more complex details (e.g. weight by ROI)
   * methods for adding neuron-region connectivity 

The generated OWL must have an IRI = resolveable URL pointing to location of stored OWL file. Loading will then be a simple matter of adding this URL to the triple store config. 

## Tech spec 

* Python code will generate Robot templates which can then be used to generate OWL for loading into the triple store. 
* An additional MakeFile will drive generation of OWL using ROBOT (including setting OWL file IRI)
* The relevant neurons and their identifiers will be found using VFB_connect to query VFB to generate simple lookups for converting between VFB IDs and external IDs
* Connectomic reports from external sites may be generated as Pandas tables, allowing efficient column based methods to be used for ID conversion.


## Architecture

Suggested: 
 - Simple wrapper class for connections
 - runner script with argparse for specific template generation jobs




