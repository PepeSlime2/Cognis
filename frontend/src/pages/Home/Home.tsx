import styles from "../Home/home.module.css";

import TopSidebar from "../../components/TopSideBar/topSideBar";
import MainContent from "../../components/MainContent/mainContent";
import type { ProviderConnection } from "../../api/client";

type HomeProps = {
    onLogout: () => void | Promise<void>
    connections: Record<string, ProviderConnection>
}

const Home = ({ onLogout, connections }: HomeProps) =>{
    return(
        <div className={styles.homeContainer}>
            <div className={styles.topSideBarContainer}>
                <TopSidebar onLogout={onLogout} connections={connections} />
            </div>
            <div className={styles.mainContentContainer}> 
                <MainContent />
            </div>
        </div>
    )
}

export default Home;