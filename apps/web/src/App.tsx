import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Shell } from "./app/Shell";
import { EvalPage } from "./features/eval/EvalPage";
import { ClassroomPage } from "./features/player/ClassroomPage";
import { CatalogPage } from "./features/catalog/CatalogPage";

/** 路由:列表页有壳(Shell),课堂页沉浸(不套壳) */
const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <CatalogPage /> },
      { path: "eval", element: <EvalPage /> },
    ],
  },
  { path: "/c/:courseId", element: <ClassroomPage /> },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
