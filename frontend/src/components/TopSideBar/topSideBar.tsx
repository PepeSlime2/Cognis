import styles from "../TopSideBar/topSideBar.module.css";
import { useEffect, useState } from "react";

import iconTrello from "../../assets/trelloicon.png";
import iconGirHub from "../../assets/github-white-icon.webp";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear } from '@fortawesome/free-solid-svg-icons';
import { faXmark } from "@fortawesome/free-solid-svg-icons";

type Connection = { username: string };
type TopSideBarProps = {
  onLogout: () => void;
};

const TopSideBar = ({ onLogout }: TopSideBarProps) => {
  const [connections, setConnections] = useState<Record<string, Connection>>({});

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => setConnections(payload?.connections ?? {}));
  }, []);

  const connectTrello = async () => {
    const response = await fetch('/api/auth/trello/authorize-url', { credentials: 'include' });
    if (!response.ok) throw new Error('Não foi possível iniciar a conexão com o Trello');
    const { authorize_url: authorizeUrl } = await response.json();
    window.location.href = authorizeUrl;
  };

  return (
        <div className={styles.sideBar}>
          <div className={styles.topSideBarContainer}>
            <div className={styles.topSideBarTitle}>
              <p>Fontes de Dados</p>
            </div>
            <div className={styles.containerIcons}>
              <div className={styles.gitHubContainer}>
                <div className={styles.gitHubIcon}>
                  <img src={iconGirHub} alt="Github Icon" />
                  <p>GitHub</p>
                </div>
                <div className={styles.serviceStatus}>
                  <p>{connections.github ? `Conectado: ${connections.github.username}` : 'Não conectado'}</p>
                </div>
              </div>
              <button className={styles.trelloContainer} onClick={connectTrello} type="button">
                <div className={styles.trelloIcon}>
                  <img src={iconTrello} alt="Trello Icon" />
                  <p>Trello</p>
                </div>
                <div className={styles.serviceStatus}>
                  <p>{connections.trello ? `Conectado: ${connections.trello.username}` : 'Não conectado'}</p>
                </div>
              </button>
              <div className={styles.syncContainer}>
                <div className={styles.syncIcon}>
                  <FontAwesomeIcon
                    className={styles.iconReload}
                    icon="rotate-right"
                    style={{ color: "#ccc" }}
                  />
                  <div className={styles.serviceSync}>
                    <p className={styles.serviceObs}>Coleta Automática</p>
                    <p className={styles.serviceInterval}>A cada 1 hora</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className={styles.projectActiveContainer}></div>
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
            <div className={styles.perfilContainer}>
              <p>Configurações</p>
            </div>
            <div className={styles.settingsConfig}>
              <FontAwesomeIcon icon={faGear} className={styles.settingsIcon} />
            </div>
            <button onClick={onLogout} type="button">Sair</button>
          </div>
          <div className={styles.overlay}>
              <div className={styles.configModal}>
                <div className={styles.headerContainer}>
                  <div className={styles.titleContainer}>
                    Configurações Cognis
                  </div>
                  <div className={styles.closeButton}>
                    <FontAwesomeIcon icon={faXmark} />
                  </div>
                </div>
              </div>
            </div>
        </div>
  );
};

export default TopSideBar;
