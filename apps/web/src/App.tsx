import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Shell } from "./app/Shell";
import { EvalPage } from "./features/eval/EvalPage";
import { ClassroomPage } from "./features/player/ClassroomPage";
import { HomePage } from "./features/home/HomePage";
import { CourseDetailPage, LibraryPage } from "./features/library";
import { StudioPage } from "./features/studio/StudioPage";

/** 路由(甲方案·五区制):列表页有壳(Shell),课堂页沉浸(不套壳)
 *  / 学习台(继续学+推荐) /courses 课程库+详情 /studio 生成中心 /eval 观测 /c/:id 课堂 */
const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "courses", element: <LibraryPage /> },
      { path: "courses/:courseId", element: <CourseDetailPage /> },
      { path: "studio", element: <StudioPage /> },
      { path: "eval", element: <EvalPage /> },
    ],
  },
  { path: "/c/:courseId", element: <ClassroomPage /> },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
