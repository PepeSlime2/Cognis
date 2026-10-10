import styles from "../MainContent/mainContent.module.css";

const MainContent = () => {
  return (
    <div className={styles.pageContent}>
      <div className={styles.filterContainer}>
        <div>Todos</div>
        <div>Pessoas</div>
        <div>Atividades</div>
        <div>Artefatos</div>
      </div>
      <div className={styles.mainContentContainer}>
        <p>Main Content Grafos</p>
      </div>
    </div>
  );
};

export default MainContent;
