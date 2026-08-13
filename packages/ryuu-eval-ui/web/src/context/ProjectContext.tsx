import { createContext, useContext, useState } from "react";

interface ProjectContextValue {
  activeProjectId: string;
  setActiveProjectId: (id: string) => void;
}

const ProjectContext = createContext<ProjectContextValue>({
  activeProjectId: "local",
  setActiveProjectId: () => {},
});

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const [activeProjectId, setActiveProjectId] = useState("local");
  return (
    <ProjectContext.Provider value={{ activeProjectId, setActiveProjectId }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useActiveProject() {
  return useContext(ProjectContext);
}
