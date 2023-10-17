#!.pyenv/bin/python3.9

import os
import glob
from vfb_connect.cross_server_tools import VfbConnect
import neuprint as np
import navis
import flybrains
import navis.interfaces.neuprint as neu
import pandas as pd


def delete_volume_files(local_folder_path):
    # Ensure the path ends with a separator
    if not local_folder_path.endswith(os.sep):
        local_folder_path += os.sep

    # Generate file paths for all files matching the pattern "volume.*" in the specified folder
    file_paths = glob.glob(f'{local_folder_path}volume.*')
    file_paths += glob.glob(f'{local_folder_path}thumbnail*')
    # Delete each file
    for file_path in file_paths:
        try:
            os.remove(file_path)
            print(f'Successfully deleted {file_path}')
        except Exception as e:
            print(f'Could not delete {file_path}: {e}')


# Download the JRC VNC transforms
flybrains.download_jrc_vnc_transforms()

# Register the downloaded transforms
flybrains.register_transforms()

# Setup connection to the VFB Neo4j database
kbw = VfbConnect(neo_endpoint='http://kb.virtualflybrain.org:80', neo_credentials=('neo4j', os.environ.get('password')))

# Initialize the neuprint client
client = np.Client('https://neuprint.janelia.org', dataset='manc:v1.0', token=os.environ.get('NEUPRINT_TOKEN'))

# Your Cypher query
cypher_query = """
MATCH (d:DataSet {short_form:'Takemura2023'})<-[:has_source]-(i:Individual)<-[:depicts]-(ic:Individual)
-[r:in_register_with]->(tc:Template)
RETURN r.filename[0] as bodyid, r.folder[0] as folder
"""

# Execute the Cypher query using the commit_list method
output = kbw.nc.commit_list(statements=[cypher_query])

# Check for errors in the response
if output is False or not output:
    print("An error occurred while executing the Cypher query.")
    exit(1)  # Exit the script in case of an error

# Access the data key of the first item in the output list
query_data_df=pd.DataFrame(output[0]['data'])['row'].apply(pd.Series)
query_data_df.columns={}

# Get the total number of items to process
total_items = len(query_data_df[0])

# Process the results
for index, result in query_data_df.iterrows:
    print(f"Processing item {index + 1} of {total_items}")
    print('result')
    # Access the row key of each result item to get the bodyid and folder values
    body_id, folder_url = result
    folder_url = folder_url.replace('http://www.virtualflybrain.org/data/', '/IMAGE_WRITE/')

    # Create the local folder if it doesn't exist
    local_folder_path = os.path.dirname(folder_url)
    os.makedirs(local_folder_path, exist_ok=True)

    # Path for the output SWC file
    filename = os.path.join(local_folder_path, f"volume.swc")

    # Path for the output obj file
    mesh_filename = os.path.join(local_folder_path, f"volume_man.obj")

    # Check if the output file already exists, if so, skip to the next iteration
    if os.path.exists(filename) and os.path.exists(mesh_filename):
        # Redo files if requested
        print(f"Redo:{os.environ.get('redo')}")
        if os.environ.get('redo') == 'true':
            print(f"File for neuron {body_id} swc and obj already exists. Removing old versions...")
            delete_volume_files(local_folder_path)
        else:
            print(f"File for neuron {body_id} swc or obj already exists. Skipping...")
            continue

    if os.path.exists(filename) or os.path.exists(mesh_filename):
        # Redo files if requested
        print(f"Redo:{os.environ.get('redo')}")
        if os.environ.get('redo') == 'true':
            print(f"File for neuron {body_id} swc or obj already exists. Removing old versions...")
            delete_volume_files(local_folder_path)

    try:

        if not os.path.exists(filename):
            # Download skeleton
            neuron = neu.fetch_skeletons(body_id, heal=True)

            # Transform neuron data from MANC to JRCVNC2018U via JRCVNC2018M
            transformed_neuron = navis.xform_brain(neuron, source='MANCraw', target='JRCVNC2018U', via='JRCVNC2018M')
            # Check for warnings
            if not transformed_neuron:
                print(f"Warning: No skeleton data available for neuron {body_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
            # Save to SWC file
            navis.write_swc(transformed_neuron, filename)
            print(f"Written to {filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
        if not os.path.exists(mesh_filename):
            # Download mesh
            mesh_neuron = neu.fetch_mesh_neuron(body_id, missing_mesh='warn')

            # Transform neuron mesh data from MANC to JRCVNC2018U via JRCVNC2018M
            transformed_mesh_neuron = navis.xform_brain(mesh_neuron, source='MANCraw', target='JRCVNC2018U',
                                                        via='JRCVNC2018M')
            # Check for warnings
            if not transformed_mesh_neuron:
                print(f"Warning: No mesh data available for neuron {body_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
            # Save to obj file
            navis.write_mesh(transformed_mesh_neuron, mesh_filename)
            print(f"Written to {mesh_filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
    except Exception as e:
        print(f"Warning: Failed to process neuron {body_id}. Error: {e}")



###backup
#!.pyenv/bin/python3.9

import os
import glob
from vfb_connect.cross_server_tools import VfbConnect
import neuprint as np
import navis
import flybrains
import navis.interfaces.neuprint as neu


def delete_volume_files(local_folder_path):
    # Ensure the path ends with a separator
    if not local_folder_path.endswith(os.sep):
        local_folder_path += os.sep

    # Generate file paths for all files matching the pattern "volume.*" in the specified folder
    file_paths = glob.glob(f'{local_folder_path}volume.*')
    file_paths += glob.glob(f'{local_folder_path}thumbnail*')
    # Delete each file
    for file_path in file_paths:
        try:
            os.remove(file_path)
            print(f'Successfully deleted {file_path}')
        except Exception as e:
            print(f'Could not delete {file_path}: {e}')


# Download the JRC VNC transforms
flybrains.download_jrc_vnc_transforms()

# Register the downloaded transforms
flybrains.register_transforms()

# Setup connection to the VFB Neo4j database
kbw = VfbConnect(neo_endpoint='http://kb.virtualflybrain.org:80', neo_credentials=('neo4j', os.environ.get('password')))

# Initialize the neuprint client
client = np.Client('https://neuprint.janelia.org', dataset='manc:v1.0', token=os.environ.get('NEUPRINT_TOKEN'))

# Your Cypher query
cypher_query = """
MATCH (d:DataSet {short_form:'Takemura2023'})<-[:has_source]-(i:Individual)<-[:depicts]-(ic:Individual)
-[r:in_register_with]->(tc:Template)
RETURN r.filename[0] as bodyid, r.folder[0] as folder
"""

# Execute the Cypher query using the commit_list method
output = kbw.nc.commit_list(statements=[cypher_query])

# Check for errors in the response
if output is False or not output:
    print("An error occurred while executing the Cypher query.")
    exit(1)  # Exit the script in case of an error

# Access the data key of the first item in the output list
query_data = output[0]['data']

# Get the total number of items to process
total_items = len(query_data)

# Process the results
for index, result in query_data:
    print(f"Processing item {index + 1} of {total_items}")
    print('result')
    # Access the row key of each result item to get the bodyid and folder values
    body_id, folder_url = result['row']
    folder_url = folder_url.replace('http://www.virtualflybrain.org/data/', '/IMAGE_WRITE/')

    # Create the local folder if it doesn't exist
    local_folder_path = os.path.dirname(folder_url)
    os.makedirs(local_folder_path, exist_ok=True)

    # Path for the output SWC file
    filename = os.path.join(local_folder_path, f"volume.swc")

    # Path for the output obj file
    mesh_filename = os.path.join(local_folder_path, f"volume_man.obj")

    # Check if the output file already exists, if so, skip to the next iteration
    if os.path.exists(filename) and os.path.exists(mesh_filename):
        # Redo files if requested
        print(f"Redo:{os.environ.get('redo')}")
        if os.environ.get('redo') == 'true':
            print(f"File for neuron {body_id} swc and obj already exists. Removing old versions...")
            delete_volume_files(local_folder_path)
        else:
            print(f"File for neuron {body_id} swc or obj already exists. Skipping...")
            continue

    if os.path.exists(filename) or os.path.exists(mesh_filename):
        # Redo files if requested
        print(f"Redo:{os.environ.get('redo')}")
        if os.environ.get('redo') == 'true':
            print(f"File for neuron {body_id} swc or obj already exists. Removing old versions...")
            delete_volume_files(local_folder_path)

    try:

        if not os.path.exists(filename):
            # Download skeleton
            neuron = neu.fetch_skeletons(body_id, heal=True)

            # Transform neuron data from MANC to JRCVNC2018U via JRCVNC2018M
            transformed_neuron = navis.xform_brain(neuron, source='MANCraw', target='JRCVNC2018U', via='JRCVNC2018M')
            # Check for warnings
            if not transformed_neuron:
                print(f"Warning: No skeleton data available for neuron {body_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
            # Save to SWC file
            navis.write_swc(transformed_neuron, filename)
            print(f"Written to {filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
        if not os.path.exists(mesh_filename):
            # Download mesh
            mesh_neuron = neu.fetch_mesh_neuron(body_id, missing_mesh='warn')

            # Transform neuron mesh data from MANC to JRCVNC2018U via JRCVNC2018M
            transformed_mesh_neuron = navis.xform_brain(mesh_neuron, source='MANCraw', target='JRCVNC2018U',
                                                        via='JRCVNC2018M')
            # Check for warnings
            if not transformed_mesh_neuron:
                print(f"Warning: No mesh data available for neuron {body_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
            # Save to obj file
            navis.write_mesh(transformed_mesh_neuron, mesh_filename)
            print(f"Written to {mesh_filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
    except Exception as e:
        print(f"Warning: Failed to process neuron {body_id}. Error: {e}")