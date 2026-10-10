import styles from "../Home/home.module.css";

import TopSidebar from "../../components/TopSideBar/topSideBar";
import MainContent from "../../components/MainContent/mainContent";

type HomeProps = {
    onLogout: () => void
}

const Home = ({ onLogout }: HomeProps) =>{
    return(
        <div className={styles.homeContainer}>
            <div className={styles.topSideBarContainer}>
                <TopSidebar onLogout={onLogout} />
            </div>
            <div className={styles.mainContentContainer}> 
                <MainContent />
            </div>
        </div>
    )
}

export default Home;