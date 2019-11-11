import pandas as pd
import numpy as np
import json
import os
from build_network import controlGroupAffiliation

from sklearn.linear_model import LinearRegression
from datetime import timedelta
from datetime import datetime
def inferStay():
    '''
    Infers how long (in days) a user spent at the Media Lab.
    The start date is inferred from the first project.
    The end data is inferred either from the last project, from the fact that the user is still active, or is imputed based on the user's group, number of projects, and how long ago they joined.
    '''
    firstRecord = loadProjects()[['username','start_on']].drop_duplicates().dropna()
    firstRecord['start_on'] = firstRecord['start_on'].apply(lambda x: datetime.strptime(x, '%Y-%m-%d'))
    firstRecord = firstRecord.groupby('username').min().reset_index()

    lastRecord = loadProjects()[['username','end_on']].drop_duplicates().dropna()
    lastRecord['end_on'] = lastRecord['end_on'].apply(lambda x: datetime.strptime(x, '%Y-%m-%d'))
    lastRecord = lastRecord.groupby('username').max().reset_index()

    nprojs = loadProjects()[['username','slug']].drop_duplicates().groupby('username').count().reset_index()

    ml_status = loadUsers()[['USERNAME','ML_STATUS']].rename(columns={"USERNAME":'username'})

    groupAfilliation = controlGroupAffiliation(loadUsers()).rename(columns={'USERNAME':'username'}).drop('is_affiliate',1)

    refDate = datetime.strptime('2019-06-01', '%Y-%m-%d')
    users = pd.merge(pd.merge(pd.merge(pd.merge(firstRecord,lastRecord,how='outer'),ml_status,how='left'),nprojs,how='left'),groupAfilliation,how='left')
    users.loc[users['ML_STATUS']==True,'end_on'] = refDate
    users.loc[users['end_on']>refDate,'end_on'] = np.nan
    users['diff'] = (users['end_on']-users['start_on']).apply(lambda x: x.days)
    users['diff2ref'] = (refDate-users['start_on']).apply(lambda x: x.days)
    print(len(set(users['username'])),len(users))

    to_impute = users[users['ML_STATUS']==False]

    inputData = to_impute[~to_impute['diff'].isna()][['ML_GROUP','slug','diff2ref']]
    inputData['slug'] = np.log(inputData['slug'])
    outputData = to_impute[~to_impute['diff'].isna()]['diff'].values
    outSample = to_impute[to_impute['diff'].isna()][['ML_GROUP','slug','diff2ref']]
    outSample['slug'] = np.log(outSample['slug'])

    for column in inputData.columns:
        if inputData[column].dtype==object:
            dummyCols=pd.get_dummies(inputData[column])
            dummyColsOut=pd.get_dummies(outSample[column])
            inputData=inputData.join(dummyCols)
            outSample=outSample.join(dummyColsOut)
            del inputData[column]
            del outSample[column]
    for c in set(inputData.columns).difference(set(outSample.columns)):
        outSample[c] = 0

    outSample = outSample[inputData.columns.values.tolist()]

    model_1=LinearRegression()
    model_1.fit(inputData,outputData)

    to_impute = to_impute[to_impute['diff'].isna()]
    to_impute['diff'] = list(model_1.predict(outSample))

    users = pd.concat([users[~users['diff'].isna()],to_impute])
    users.loc[users['diff']>users['diff2ref'],'diff'] = users[users['diff']>users['diff2ref']]['diff2ref']

    users['end_on'] = users['start_on'] + users['diff'].apply(lambda x: timedelta(days=x))
    return users

def inferOverlap(users,userSet=None):
	if userSet is None:
		userSet = set(users['username'])
	timeOverlap = []
	for u1 in userSet:
		u1_start = users[users['username']==u1]['start_on'].values[0]
		u1_end   = users[users['username']==u1]['end_on'].values[0]
		for u2 in userSet:
			if u1!=u2:
				u2_start = users[users['username']==u2]['start_on'].values[0]
				u2_end   = users[users['username']==u2]['end_on'].values[0]
				dt = (min(u1_end,u2_end)-max(u1_start,u2_start)).astype('timedelta64[D]')/np.timedelta64(1, 'D')
				timeOverlap.append((u1,u2,dt))
	timeOverlap = pd.DataFrame(timeOverlap,columns=['username_s','username_t','overlap'])
	return timeOverlap

def parseUsers(projects):
	'''
	Parses the users from the projects provided in a dataframe.

	Parameters
	----------
	projects : pandas.DataFrame
	    Table of projects. Must have columns 'people' and a 'slug'.
	'''
	out = []
	for slug,people in projects[['slug','people']].values:
		if len(people)!=0:
			for person in people:
				if '@media.mit.edu' in person: # Keep only media lab users
					out.append((slug,person.replace('@media.mit.edu','').strip()))
	return pd.DataFrame(out,columns=['slug','username'])

def loadProjects(in_path='../Data/'):
	'''
	Loads projects into a DataFrame from a given path. It takes care of putting user data into first normal form.

	Parameters
	----------
	in_path : str (optional)
		Path of projects-active.json and projects-inactive.json.
	'''
	fnameActive = 'projects-active.json'
	fnameInactive = 'projects-inactive.json'
	activeProjects   = pd.read_json(os.path.join(in_path,fnameActive))
	inactiveProjects = pd.read_json(os.path.join(in_path,fnameInactive))
	activeProjects['is_active'] = True
	inactiveProjects['is_active'] = False

	activeProjects = pd.merge(parseUsers(activeProjects),activeProjects.drop(['people','groups'],1))
	inactiveProjects = pd.merge(parseUsers(inactiveProjects),inactiveProjects.drop(['people','groups'],1))

	projects = pd.concat([inactiveProjects,activeProjects])
	return projects

def loadUsers(in_path='../Data'):
	'''
	Loads raw data about ML users. 

	Parameters
	----------
	in_path : str (optional)
		Path to mlpeople.csv.
	'''
	people = pd.read_csv(os.path.join(in_path,'mlpeople.csv'))
	return people

def generateNework(projects,keepProjectData=False):
	'''
	Generates network of users connected when they worked together on a project.

	Parameters
	----------
	projects : pandas.DataFrame
		Table with columns slug and username

	Returns
	-------
	net : pandas.DataFrame
		Table with username_s, username_t, and number of projets.
	'''
	if keepProjectData:
		df = projects[['slug','username','title']]
		net = pd.merge(df.rename(columns={'username':'username_s'}),df.rename(columns={'username':'username_t'}))
		net = net[net['username_s']!=net['username_t']]
		net = net[['username_s','username_t','slug','title']]
	else:
		df = projects[['slug','username']]
		net = pd.merge(df.rename(columns={'username':'username_s'}),df.rename(columns={'username':'username_t'}))
		net = net[net['username_s']!=net['username_t']]
		net = net.groupby(['username_s','username_t']).count().rename(columns={'slug':'n_projects'}).reset_index()
	return net

def formatNetwork(net):
	'''
	Formats the network into a dictonary that can be written in a json file.

	Parameters
	----------
	net : pandas.DataFrame
		Table with username_s,username_t, and n_projects.
	'''
	net['username_t*n_projects']=net[['username_t','n_projects']].values.tolist()
	return dict(net.groupby('username_s')['username_t*n_projects'].apply(list))

def filterProjects(projects):
	'''
	Filter projects if needed (by date, for example)
	'''
	drop_list = ['scratch-in-practice','ml-learning-fellows-program','learning-creative-learning'] # 'scratch'
	projects = projects[~projects['slug'].isin(drop_list)]
	return projects

def main():
	out_path = '../ProxymixABM/includes/'
	projects = loadProjects()

	projects = filterProjects(projects)

	net = generateNework(projects)
	data_out = formatNetwork(net)
	with open(os.path.join(out_path,'project-network.json'), 'w') as fp:
		json.dump(data_out, fp)

if __name__ == '__main__':
	main()