import getpass
import sys
import requests
import boto3
import hvac
import yaml
from shlex import quote
from yaml import load, dump

debug_mode = False
verbose_mode = False
clear = "\n" * 100
sg_id_isolamento = 0000
session = {}

yaml_params = yaml.load(open('.\\config.yaml', 'r', encoding="utf-8"), Loader=yaml.SafeLoader)
environments = yaml_params['environments']
aws_vault_secret_name = yaml_params['aws_vault_secret_name']

def setup_env(env, region):
    get_aws_credentials(env)
    create_aws_session(environments[env], region)

def get_aws_credentials(env):
    if environments[env]['aws_access_key_id'] == '' and  environments[env]['aws_secret_access_key'] == '':
        client = hvac.Client(url=environments[env]['vault-url'], token=environments[env]['vault-token'], timeout=60)
        vault = client.read('secret/' + aws_vault_secret_name)
        environments[env]['aws_access_key_id'] = vault['data']['aws_access_key_id']
        environments[env]['aws_secret_access_key'] = vault['data']['aws_secret_access_key']

        for region in environments[env]['regions']:
            if region['sg_isolation'] == '':                                                            # region     security group id
                region['sg_isolation'] = vault['data']['sg-' + region['name']] # EG.: environment['TI']['us-east-1']/['sg_isolation'] = vault['data']['sg-us-east-1']

        print('Credenciais da AWS obtidas no vault')
    
    else:
        print('Credenciais da AWS já carregadas...')

def create_aws_session(environment, region):
    global session
    session =  boto3.session.Session(aws_access_key_id=environment['aws_access_key_id'], 
    aws_secret_access_key=environment['aws_secret_access_key'], region_name=region)

def list_instances():
    ec2 = session.resource('ec2')
    instances = ec2.instances.filter()
    return instances

def get_instance(id):
    ec2 = session.resource('ec2')
    instance = ec2.Instance(id)
    return instance

def print_instance_details(instance):
    print("""\
\n=======================================================================
\n
    NOME : """+instance.key_name+"""
    ID   : """+ instance.id + """
    TIPO : """+ instance.instance_type + """
    SECURITY GROUPS : """)
    for group in instance.security_groups:
        print("""\
        NOME : """+ group['GroupName'] +"""
        ID   : """+ group['GroupId']
        )
        detail_security_group(group['GroupId'])

def remove_sg(sg_id, instance):
    all_sg_ids = [sg['GroupId'] for sg in instance.security_groups]  

    if sg_id in all_sg_ids:                                          
      all_sg_ids.remove(sg_id)                                       
      instance.modify_attribute(Groups=all_sg_ids)                   

def remove_all_sgs(instance):
    instance.modify_attribute(Groups=[])

def attach_sg(sg_id, instance):
    instance.modify_attribute(Groups=sg_id)

def start_isolation(instance_id, environment=None, region=None):
    found = False
    if not environment:
        for key, val in environments.items():
            if not region:
                if found:
                    break
                for reg in val['regions']:
                    if found:
                        break
                    setup_env(env=key, region=reg['name'])
                    try:
                        isolate(instance_id, key)
                        found = True
                    except Exception:
                        print('[INFO] - Did not found machine in ' + reg + '/' + key)
                        pass
            else:
                if found:
                    break
                setup_env(env=key, region=region)
                try:
                    isolate(instance_id, key)
                    found = True
                except Exception:
                    print('[INFO] - Did not found machine in ' + region + '/' + key)
                    pass
    else:
        if not region:
            for reg in val['regions']:
                if found:
                    break
                setup_env(env=environment, region=reg['name'])
                try:
                    isolate(instance_id, environment)
                    found = True
                except Exception:
                    print('[INFO] - Did not found machine in ' + reg + '/' + environment)
                    pass
        else:
            setup_env(env=environment, region=region)
            try:
                isolate(instance_id, environment)
            except Exception:
                print('[INFO] - Did not found machine in ' + region + '/' + environment)
                pass        


def isolate(instance_id, environment):
    try:
        instance = get_instance(instance_id)
        print(clear)
        print_instance_details(instance)
        if get_yes_or_no('\nConfirmar o isolamento da máquina ' + instance.key_name + '?'):
            print(clear + '\nExecutando o isolamento da máquina...')
            try:
                # remove_all_sgs(instance.id)
                for region in environments[environment]['regions']:
                    try:
                        attach_sg(region['sg_isolation'], instance)
                    except Exception:
                        pass
                print(""""""+clear+"""\n=======================================================================
                    Resultado do isolamento """)
                instance = get_instance(instance_id)
                print_instance_details(instance)

            except Exception:
                pass
        else:
            print('\nOperação abortada pelo usuário!')
    except Exception:
        pass


def detail_security_group(sg_id):
    try:
        response = session.client('ec2').describe_security_groups(GroupIds=[sg_id])
        for group in response['SecurityGroups']:
            
            print("""\
        DESCRIÇÃO :""" + group['Description'] + '\n')
            
            print("""\
        PERMISSÕES DE ENTRADA :""")
            
            for permission in group['IpPermissions']:
                print("""\
            PROTOCOLO : """ + " ALL" if permission['IpProtocol'] == '-1'  else 
            """\
            PROTOCOLO : """ + permission['IpProtocol'])
                
                for ip_range in permission['IpRanges']:
                    print("""\
                RANGE :""" + ip_range['CidrIp'] + '\n')
            print("""\
        PERMISSÕES DE SAÍDA :""")
            
            for permission in group['IpPermissionsEgress']:
                print("""\
            PROTOCOLO : """ + " ALL" if permission['IpProtocol'] == '-1'  
            else """\
            PROTOCOLO : """ + permission['IpProtocol'])
                for ip_range in permission['IpRanges']:
                    print("""\
                RANGE :""" + ip_range['CidrIp']+'\n')
            
    except Exception as e:
        print(e)
        pass

def get_numeric(range_min, range_max):
    while True:
        try:
            res = int(input('Opção: '))
            if res not in range(range_min, range_max):
                raise ValueError('[ERRO]')
            break
        except (ValueError, NameError):
            print("[ERRO] - Informe uma opção válida!")
    return res


def get_yes_or_no(question, default="s"):
    valid = {"sim": True, "s": True, "si": True,
             "nao": False, "n": False, "na": False, "não": False}

    while True:
        if default == "s":
            sys.stdout.write(question + " [S/n] ")
        else:
            sys.stdout.write(question + " [s/N] ")
        choice = quote(input().lower())

        if choice == '\'\'':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("[ERRO] - Por favor responda com 'sim' ou 'nao' "
                             "('s' ou 'n').\n")


def print_env_pick_menu(headline):
    i=2
      
    print("""\
"""+clear+"""
"""+headline+"""
        Digite 1 para todos os ambientes          """)
    for key, val in environments.items():
        print("\tDigite " + str(i) + " para " + str(key) + " (somente)")
        i += 1
    
    print("""\tDigite """ + str(i) + """ para retornar ao menu principal
        Digite 0 para sair\n""")
    return i

def get_env():
    headline = """
# ====================== PASSO 2 =========================== #\n
    Informe o(s) ambiente(s) que deseja consultar:\n"""

    max_opt = print_env_pick_menu(headline)

    opt = get_numeric(0, max_opt + 1)
    
    print('[INFO] - Opção ' + str(opt) + ' selecionada') if verbose_mode else 0
    if opt == 0:
        sys.exit(0)
    elif opt == 1:
        return environments.keys()
    elif opt >= 2 and opt < max_opt:
        return list(environments.keys())[opt-2]
    elif opt == max_opt:
        main()

def main():
    print(clear)
    global debug_mode
    global verbose_mode

    for arg in sys.argv[1:]:
        if arg == '-d':
            debug_mode = True
        elif arg == '-v':
            verbose_mode = True

    if debug_mode:
        print('\n\n\n*******    EXECUTANDO APLICAÇÃO EM MODO DEBUG    *******')

    print("""\

        ███████╗ ██████╗██████╗     ██╗
        ██╔════╝██╔════╝╚════██╗    ██║
        █████╗  ██║      █████╔╝    ██║
        ██╔══╝  ██║     ██╔═══╝     ██║
        ███████╗╚██████╗███████╗    ██║
        ╚══════╝ ╚═════╝╚══════╝    ╚═╝                                    
                                    
    Script de Isolamento de máquinas EC2 na AWS                        

                                        v 1.0

                                    CVC Corp 2019     
                                    By Leonardo Molina 
==========================================================
    Selecione a opção desejada:\n          
        Digite 1 para isolar uma máquina pelo ID
        Digite 2 para listar as máquinas por ambiente
        Digite 0 para sair """)

    opt = get_numeric(0,3)
    
    print('[INFO] - Opção ' + str(opt) + ' selecionada') if verbose_mode else 0
    if opt == 0:
        sys.exit(0)
    elif opt == 1:
        target_ec2_id = input('Informe o ID da máquina a ser isolada:')
        start_isolation(instance_id=target_ec2_id)
    elif opt == 2:
        envs = get_env()
        for env in envs:
            print(clear + """\n 
                    Listando máquinas EC2 em """ + env + '...\n\n')
            for region in region_names:
                setup_env(env, region)
                instances = list_instances()
                print("""\n=======================================================================\n
            [INFO] - """ + str(len([instance for instance in instances])) + ' Instâncias encontradas em ' + region)
                for instance in instances:
                    print_instance_details(instance)
            if get_yes_or_no('\nDeseja executar o isolamento de alguma máquina?', 'n'):
                target_ec2_id = input('Informe o ID da máquina a ser isolada:')
                start_isolation(instance_id=target_ec2_id, environment=env)
                break
    
    if get_yes_or_no('\nDeseja continuar a execução?'):
        main()
    else:
        sys.exit(0)
    
if __name__ == '__main__':
    main()