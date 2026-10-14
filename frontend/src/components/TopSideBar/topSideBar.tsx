import styles from "../TopSideBar/topSideBar.module.css";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, projectsQueryKey } from "../../api/client";
import type { ProjectSummary, ProviderConnection } from "../../api/client";

import iconTrello from "../../assets/trelloicon.png";
import iconGirHub from "../../assets/github-white-icon.webp";
import cognisLogo from "../../assets/CognisLogotipo.png";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear } from '@fortawesome/free-solid-svg-icons';

type TopSideBarProps = {
  onLogout: () => void | Promise<void>;
  connections: Record<string, ProviderConnection>;
  projectId?: string;
};

const TopSideBar = ({ onLogout, connections, projectId }: TopSideBarProps) => {
  const navigate = useNavigate();
  const [connectionError, setConnectionError] = useState('');
  const projectsQuery = useQuery({
    queryKey: projectsQueryKey,
    queryFn: () => api.get<ProjectSummary[]>('/projects'),
  });

  const connectGithub = async () => {
    setConnectionError('');
    try {
      const payload = await api.get<{ authorize_url: string }>('/auth/github/login');
      window.location.href = payload.authorize_url;
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : 'Não foi possível iniciar a conexão com o GitHub.');
    }
  };

  const connectTrello = async () => {
    setConnectionError('');
    try {
      const payload = await api.get<{ authorize_url: string }>('/auth/trello/authorize-url');
      window.location.href = payload.authorize_url;
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : 'Não foi possível iniciar a conexão com o Trello.');
    }
  };

  return (
    <aside className={styles.sideBar} aria-label="Navegação e fontes de dados">
      <div className={styles.brandHeader}>
        <div className={styles.brandLogo} onClick={() => navigate('/')} role="button" tabIndex={0} title="COGNIS">
          <img src={cognisLogo} alt="COGNIS" className={styles.brandLogoImg} />
        </div>
        <span className={styles.brandTag}>v1.2</span>
      </div>

      <div className={styles.topSideBarContainer}>
        <div className={styles.topSideBarTitle}>
          <span>Fontes de Dados</span>
        </div>
        <div className={styles.containerIcons}>
          <button className={styles.gitHubContainer} onClick={() => void connectGithub()} type="button">
            <div className={styles.gitHubIcon}>
              <img src={iconGirHub} alt="GitHub" />
              <p>GitHub</p>
            </div>
            <div className={styles.serviceStatus}>
              <span className={connections.github ? styles.statusDotConnected : styles.statusDotDisconnected} />
              <p>{connections.github ? `Conectado: ${connections.github.username}` : 'Não conectado'}</p>
            </div>
          </button>
          <button className={styles.trelloContainer} onClick={() => void connectTrello()} type="button">
            <div className={styles.trelloIcon}>
              <img src={iconTrello} alt="Trello" />
              <p>Trello</p>
            </div>
            <div className={styles.serviceStatus}>
              <span className={connections.trello ? styles.statusDotConnected : styles.statusDotDisconnected} />
              <p>{connections.trello ? `Conectado: ${connections.trello.username}` : 'Não conectado'}</p>
            </div>
          </button>
          {connectionError && <p className={styles.serviceError} role="alert">{connectionError}</p>}
          <div className={styles.syncContainer}>
            <div className={styles.syncIcon}>
              <FontAwesomeIcon
                className={styles.iconReload}
                icon="rotate-right"
              />
              <div className={styles.serviceSync}>
                <p className={styles.serviceObs}>Coleta Automática</p>
                <p className={styles.serviceInterval}>
                  {(() => {
                    const activeProject = projectsQuery.data?.find((p) => p.id === projectId)
                    if (!activeProject) return 'Selecione um projeto'
                    if (!activeProject.auto_sync) return 'Manual (Desativada)'
                    switch (activeProject.sync_interval_min) {
                      case 15:
                        return 'A cada 15 min'
                      case 30:
                        return 'A cada 30 min'
                      case 60:
                        return 'A cada 1 hora'
                      case 360:
                        return 'A cada 6 horas'
                      case 1440:
                        return 'A cada 24 horas'
                      default:
                        return `A cada ${activeProject.sync_interval_min} min`
                    }
                  })()}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className={styles.projectActiveContainer}>
        <label htmlFor="active-project">Projeto ativo</label>
        <select
          id="active-project"
          value={projectId ?? ''}
          onChange={(event) => navigate(event.target.value ? `/p/${event.target.value}` : '/')}
          disabled={projectsQuery.isPending || projectsQuery.isError}
        >
          <option value="">Todos os projetos</option>
          {projectsQuery.data?.map((project) => (
            <option key={project.id} value={project.id}>{project.name}</option>
          ))}
        </select>
        {projectsQuery.isPending && <p>Carregando projetos...</p>}
        {projectsQuery.isError && <p className={styles.serviceError} role="alert">Não foi possível carregar projetos.</p>}
        {projectsQuery.data?.length === 0 && <p>Nenhum projeto criado.</p>}
      </div>

      <div className={styles.midSideBarContainer}>
        <div className={styles.processoContainer}>
          <div className={styles.titleProcessamento}>
            Relatórios
          </div>
          <div className={styles.contentContainer}>
            <div className={styles.serviceContent}>
              Sprint
            </div>
            <div className={styles.serviceContent}>
              Gerencial
            </div>
            <div className={styles.serviceContent}>
              Individual
            </div>
            <div className={styles.serviceContent}>
              Gargalos
            </div>
            <div className={styles.serviceContent}>
              Colaboração
            </div>
          </div>
        </div>
      </div>

      <div className={styles.settingsContainer}>
        <button className={styles.perfilContainer} onClick={() => navigate('/settings')} type="button">
          <FontAwesomeIcon icon={faGear} className={styles.settingsIcon} />
          <p>Configurações</p>
        </button>
        <button className={styles.logoutButton} onClick={() => void onLogout()} type="button">
          Sair
        </button>
      </div>
    </aside>
  );
};

export default TopSideBar;
