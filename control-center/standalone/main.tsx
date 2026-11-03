import { createRoot } from "react-dom/client";
import { Console } from "@/components/Console";
import { installMockServer } from "./mockServer";

installMockServer();
createRoot(document.getElementById("root")!).render(<Console />);
