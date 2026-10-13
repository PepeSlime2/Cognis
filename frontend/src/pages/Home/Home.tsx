import styles from "../Home/home.module.css";

import TopSidebar from "../../components/TopSideBar/topSideBar";
import MainContent from "../../components/MainContent/mainContent";
import GraphShell from "../../components/Graph/GraphShell";
import type { ProviderConnection } from "../../api/client";

type HomeProps = {
    onLogout: () => void | Promise<void>
    connections: Record<string, ProviderConnection>
    projectId?: string
}

const Home = ({ onLogout, connections, projectId }: HomeProps) =>{
    if (projectId) {
        return <GraphShell projectId={projectId} onLogout={onLogout} connections={connections} />
    }

    return(
        <div className={styles.homeContainer}>
            <div className={styles.topSideBarContainer}>
                <TopSidebar onLogout={onLogout} connections={connections} projectId={projectId} />
            </div>
            <div className={styles.mainContentContainer}> 
                <MainContent projectId={projectId} />
            </div>
        </div>
    )
}

export default Home;