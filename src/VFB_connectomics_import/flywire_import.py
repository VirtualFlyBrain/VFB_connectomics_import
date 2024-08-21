#    Functions for grabbing FlyWire neurons, including meshes/skeletons/connectivity/annotations
#    Warning: be careful with versions and rootid mappings for this dataset. Contact Philipp Schlegel at FlyWire for up to date advice (suggest using slack)

from fafbseg import flywire
import fafbseg
import navis
import pandas as pd
import flybrains
import os
from vfb_connect.cross_server_tools import VfbConnect

#setup flywire credentials
#flywire.set_chunkedgraph_secret("47576875e49eeb999396a0e73de0cf31")

#setup flywire default dataset - in the future hopefully this will just be prod
#flywire.set_default_dataset('flat_630')

def generate_curation_tsv(annotations_tsv_path):
    '''generate anat_ tsv for loading neuprint neurons via the VFB curation interface

    Parameters
    ----------
    query  :        string
                    Cypher query for neuprint, must return neuron node(s)
    '''

    #we're using an intermediate release here so there is no matching materialisation. So we need to load our csv from Philipp, map back to mat 630 and then load from those root_ids. ez pz.
    neuron_annotations_df = pd.read_csv(annotations_tsv_path, sep='\t')
    neuron_annotations_df.dropna(subset='vfb_id', inplace=True)

    ## map back to 630 and drop those that don't - this uses supervoxels
    mapped_ids=flywire.supervoxels_to_roots(neuron_annotations_df.supervoxel_id, timestamp='mat_783')

    ## add mapped ids to df and compare to current ids, check for dups
    neuron_annotations_df['root_783_u'] = mapped_ids

    #which ones are inconsistent between the supp info and 783
    all(neuron_annotations_df['root_id'] == neuron_annotations_df['root_783_u'])
    neuron_annotations_df[neuron_annotations_df['root_783_u'] != neuron_annotations_df['root_id']] ##TODO have a look at where a single 630 neuron maps to many in current. (looks like visual mashed together so far) - confirmed many are visual and many are not on the codex, presumably for the same reason. will drop these for now

    # find dups
    neuron_annotations_df['root_783_u'].value_counts()
    mat_738_dups = neuron_annotations_df[neuron_annotations_df['root_783_u'].duplicated(keep=False)].sort_values(by='root_783_u')

    #drop dups TODO check with robbie if this needs to be expanded into something smarter
    neurons_df = neuron_annotations_df[~neuron_annotations_df['root_783_u'].duplicated(keep=False)]

    # make curation tsv
    curation_tsv = pd.DataFrame()
    curation_tsv['anat_id'] = 'VFB_' + neurons_df[['vfb_id']]
    curation_tsv['filename'] = neurons_df[['root_783_u']]
    curation_tsv['is_a'] = 'adult neuron'
    curation_tsv['part_of'] = 'female organism|adult brain'
    curation_tsv['label'] = 'FlyWire:' + neurons_df['root_id'].astype(str) #TODO is there an instance name?
    curation_tsv['comment'] = ''
    curation_tsv['comment'][~neurons_df['status'].isna()] = 'status-' + neurons_df['status']
    neurons_df.fillna('None', inplace=True)
    curation_tsv['comment'] = curation_tsv['comment'] + 'FlyWire classification: flow-' + neurons_df['flow'].astype(str) + ', superclass-' + neurons_df['super_class'].astype(str) + ', class-' + neurons_df['cell_class'].astype(str) + ', subclass-' + neurons_df['cell_sub_class'].astype(str) + ', cell type-' + neurons_df['cell_type'].astype(str)+ ', hemibrain type-' + neurons_df['hemibrain_type'].astype(str)
    curation_tsv['comment'] = curation_tsv['comment'] + '. FBbt_id annotation-' + neurons_df['fbbt_id'].astype(str)
    curation_tsv['comment'] = curation_tsv['comment'] + '. supervoxel id-' + neurons_df['supervoxel_id'].astype(str)
    curation_tsv['dbxrefs'] = 'flywire783:' + neurons_df['root_783_u'].astype(str) + '|' + 'flywire_supervoxel:' + neurons_df['supervoxel_id'].astype(str)

    return curation_tsv

annotations_tsv_path = '/Users/adm/Documents/GitHub/VFB_connectomics_import/src/VFB_connectomics_import/resources/Supplemental_file1_neuron_annotations_783.tsv'
annotations_tsv_path = '/Users/adm/Documents/GitHub/VFB_connectomics_import/src/VFB_connectomics_import/resources/Supplemental_file1_annotations_630.tsv'
curation_tsv=generate_curation_tsv(annotations_tsv_path)
curation_tsv.to_csv('Dorkenwald2023_curation.tsv', sep='\t', index=False)

##### scraps for testing skels/meshes, code runs on jenkins (url tbd).

## testing neuron obj sizes
testset = list(curation_tsv.filename[10000:10010])
k = flywire.get_mesh_neuron(testset, dataset='flat_783', lod=2)
s = flywire.get_skeletons(testset, dataset='783') #there are some neurons with multiple somas?

## plotting
navis.plot3d([k],backend='plotly').show(renderer='browser')
navis.plot3d([s],backend='plotly').show(renderer='browser')

#transforming
flybrains.download_jrc_transforms()
flybrains.register_transforms()
transformed_neuron = navis.xform_brain(k, source='FLYWIRE', via='JRCFIB2022M' ,target='JRC2018U')
#plot transformed against mesh
navis.plot3d([transformed_neuron, flybrains.JRC2018U],backend='plotly').show(renderer='browser')








#!.pyenv/bin/python3.9

import os
import glob
import navis
import flybrains
from fafbseg import flywire
import pandas as pd
from vfb_connect.cross_server_tools import VfbConnect

def delete_volume_files(local_folder_path):
    """
    Delete all files matching the pattern "volume.*" in the specified folder.
    :param local_folder_path: str, path to the folder containing the files to delete
    """
    # Ensure the path ends with a separator
    if not local_folder_path.endswith(os.sep):
        local_folder_path += os.sep
    # Generate file paths for all files matching the pattern "volume.*" in the specified folder
    file_paths = glob.glob(f'{local_folder_path}volume*')
    file_paths += glob.glob(f'{local_folder_path}thumbnail*')
    # Delete each file
    for file_path in file_paths:
        try:
            os.remove(file_path)
            print(f'Successfully deleted {file_path}')
        except Exception as e:
            print(f'Could not delete {file_path}: {e}')

# Download transforms
flybrains.download_jrc_transforms()

# Register the downloaded transforms
flybrains.register_transforms()

# Setup connection to the VFB Neo4j database
kbw = VfbConnect(neo_endpoint='http://kb.virtualflybrain.org:80', neo_credentials=('neo4j', os.environ.get('password')))

flywire.set_chunkedgraph_secret("47576875e49eeb999396a0e73de0cf31")

# Your Cypher query
cypher_query = '''
MATCH (d:DataSet {short_form:'Dorkenwald2023'})<-[:has_source]-(i:Individual)<-[:depicts]-(ic:Individual)
-[r:in_register_with]->(tc:Template)
RETURN r.filename[0] as root_id, r.folder[0] as folder
'''

# Execute the Cypher query using the commit_list method
output = kbw.nc.commit_list(statements=[cypher_query])

# Check for errors in the response
if output is False or not output:
    print("An error occurred while executing the Cypher query.")
    exit(1)  # Exit the script in case of an error

# Access the data key of the first item in the output list
query_data_df = pd.DataFrame(output[0]['data'])['row'].apply(pd.Series)

# Get the total number of items to process
total_items = len(query_data_df[0])

# Process the results
for index, result in query_data_df.iterrows():
    print(f"Processing item {index + 1} of {total_items}")
    # Access the row key of each result item to get the bodyid and folder values
    body_id, folder_url = result
    folder_url = folder_url.replace('http://www.virtualflybrain.org/data/', '/IMAGE_WRITE/')

    try:

        body_id = int(body_id)  # Ensure body_id is an integer

    except ValueError as e:

        print(f"Warning: body_id {body_id} is not an integer. Error: {e}")

        continue

    # Create the local folder if it doesn't exist
    local_folder_path = os.path.dirname(folder_url)
    os.makedirs(local_folder_path, exist_ok=True)

    # Path for the output SWC file
    filename = os.path.join(local_folder_path, f"volume.swc")

    # Path for the output obj file
    mesh_filename = os.path.join(local_folder_path, f"volume_man.obj")

    # Path for the output NRRD file
    nrrd_filename = os.path.join(local_folder_path, "volume.nrrd")

    # Check if the output file already exists, if so, skip to the next iteration
    if os.path.exists(filename) and os.path.exists(mesh_filename) and os.path.exists(nrrd_filename):
        # Redo files if requested
        if os.environ.get('redo') == 'true':
            print(f"File for neuron {body_id} swc and obj already exists. Removing old versions...")
            delete_volume_files(local_folder_path)
        else:
            print(f"File for neuron {body_id} swc or obj already exists. Skipping...")
            continue

    if os.path.exists(filename) or os.path.exists(mesh_filename):
        # Redo files if requested
        if os.environ.get('redo') == 'true':
            print(f"File for neuron {body_id} swc or obj already exists. Removing old versions...")
            delete_volume_files(local_folder_path)

    try:
        if not os.path.exists(filename):
            # Download skeleton
            neuron = flywire.get_skeletons(body_id, dataset='783')

            #replace the above line if the swcs are downloaded instead from
            ### this needs to be the path to the local 'sk_lod1_783_healed' folder + the root_id - ex 'c/sk_lod1_783_healed_ds2/720575940621280688.swc'
            #neuron = navis.read_swc('sk_lod1_783_healed' + root_id)

            # Transform neuron data from FLYWIRE to JRC2018U (needs via to work currently)
            transformed_neuron = navis.xform_brain(neuron, source='FLYWIRE', via='JRCFIB2022M' ,target='JRC2018U')
            # Check for warnings
            if not transformed_neuron:
                print(
                    f"Warning: No skeleton data available for neuron {body_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
            # Save to SWC file
            navis.write_swc(transformed_neuron, filename)
            print(f"Written to {filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
        else:
            print(f"File for neuron {body_id} swc already exists. Skipped...")
    except Exception as e:
        print(f"Warning: Failed to process neuron {body_id}. Error: {e}")
    try:
        if not os.path.exists(mesh_filename) or not os.path.exists(nrrd_filename):
            mesh_neuron = neu.fetch_mesh_neuron(body_id, missing_mesh='warn', lod=None)

            # Transform neuron mesh data from FLYWIRE to JRC2018U (needs via to work currently)
            transformed_mesh_neuron = navis.xform_brain(mesh_neuron, source='FLYWIRE', via='JRCFIB2022M' ,target='JRC2018U')
            # Check for warnings
            if not transformed_mesh_neuron:
                print(
                    f"Warning: No mesh data available for neuron {body_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
            if not os.path.exists(mesh_filename):
                # Save to obj file
                navis.write_mesh(transformed_mesh_neuron, mesh_filename)
                print(f"Written to {mesh_filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
        else:
            print(f"File for neuron {body_id} obj already exists. Skipped...")
    except Exception as e:
        print(f"Warning: Failed to process neuron {body_id}. Error: {e}")

    # Check if the output NRRD file already exists, if so, skip to the next iteration

    if os.path.exists(nrrd_filename):
        print(f"File for neuron {body_id} nrrd already exists. Skipping...")
        continue

    # Create NRRD via navis
    try:
        # Check for warnings
        if not transformed_mesh_neuron:
            print(
                f"Warning: No mesh data available for neuron {body_id}. Possibly outside the H5 deformation field. Trying Skeleton")
            transformed_mesh_neuron = transformed_neuron
            if not transformed_mesh_neuron:
                print(
                    f"Warning: No skeleton data available for neuron {body_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
        vx = navis.voxelize(transformed_mesh_neuron, pitch=['0.5189161 microns', '0.5189161 microns', '1.0 microns'], bounds=[[0, 627.3695649], [0, 293.1875965], [0, 173]], parallel=True)
        vx.grid = (vx.grid).astype('uint8') * 255
        navis.write_nrrd(vx, filepath=nrrd_filename, compression_level=9)
        print(f"Written to {nrrd_filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
    except Exception as e:
        print(f"Warning: Failed to create NRRD for neuron {body_id}. Error: {e}")