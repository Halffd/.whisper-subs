import subprocess
from manim import *
import sys

class DotCrossProduct(Scene):
    def construct(self):
        # Define vectors
        axis(self)
        a = np.array([2, 3, 0])
        b = np.array([-1, 1, 0])
        
        # Create vector objects
        vector_a = Arrow(ORIGIN, a, buff=0, color=BLUE)
        vector_b = Arrow(ORIGIN, b, buff=0, color=GREEN)
        
        # Create labels
        label_a = Tex(r"$\mathbf{a} = [2, 3]$", color=BLUE).next_to(vector_a, UP)
        label_b = Tex(r"$\mathbf{b} = [-1, 1]$", color=GREEN).next_to(vector_b, UP)

        # Calculate dot product and cross product
        dot_product = np.dot(a, b)
        cross_product = np.cross(a, b)

        # Display vectors
        self.play(Create(vector_a), Write(label_a))
        self.play(Create(vector_b), Write(label_b))
        self.wait(1)

        # Display dot product result
        dot_result = Tex(r"Dot Product: $\mathbf{a} \cdot \mathbf{b} = $" + str(dot_product)).to_edge(UP)
        self.play(Write(dot_result))
        self.wait(1)

        # Display cross product result
        cross_result = Tex(r"Cross Product: $\mathbf{a} \times \mathbf{b} = $" + str(cross_product)).to_edge(DOWN)
        self.play(Write(cross_result))
        self.wait(1)

        # Show area of parallelogram for cross product
        parallelogram = Polygon(ORIGIN, a, a + b, b, color=YELLOW, fill_opacity=0.3)
        self.play(Create(parallelogram))
        self.wait(2)

        # End scene
        self.play(FadeOut(vector_a), FadeOut(vector_b), FadeOut(parallelogram), FadeOut(dot_result), FadeOut(cross_result))
        self.wait(1)

# To run this code, save it to a .py file and use the command:
# manim -pql your_script.py DotCrossProduct
class ThreeAxisCrossProduct(Scene):
    def construct(self):
        # Create 3D axes
        axes = ThreeDAxes()

        # Define unit vectors along the axes
        x_vector = np.array([1, 2, -1])  # x-axis
        y_vector = np.array([-2, 1, 0])  # y-axis
        z_vector = np.array([3, -1, 1])  # z-axis

        # Create arrows for unit vectors
        arrow_x = Arrow3D(ORIGIN, x_vector, color=BLUE)
        arrow_y = Arrow3D(ORIGIN, y_vector, color=RED)
        arrow_z = Arrow3D(ORIGIN, z_vector, color=GREEN)

        # Calculate cross products
        cross_xy = np.cross(x_vector, y_vector)  # Should point in the z direction
        cross_yz = np.cross(y_vector, z_vector)  # Should point in the x direction
        cross_zx = np.cross(z_vector, x_vector)  # Should point in the y direction

        # Create arrows for cross products
        arrow_cross_xy = Arrow3D(ORIGIN, cross_xy, color=YELLOW)
        arrow_cross_yz = Arrow3D(ORIGIN, cross_yz, color=PURPLE)
        arrow_cross_zx = Arrow3D(ORIGIN, cross_zx, color=ORANGE)

        # Add the axes and arrows to the scene
        self.play(Create(axes))
        self.play(Create(arrow_x), Create(arrow_y), Create(arrow_z))
        self.wait(1)
        
        # Show cross products
        self.play(Create(arrow_cross_xy), Create(arrow_cross_yz), Create(arrow_cross_zx))
        self.wait(2)

        # Add labels for the vectors
        label_x = MathTex(r"\mathbf{i} = [1, 0, 0]").next_to(arrow_x, UP)
        label_y = MathTex(r"\mathbf{j} = [0, 1, 0]").next_to(arrow_y, LEFT)
        label_z = MathTex(r"\mathbf{k} = [0, 0, 1]").next_to(arrow_z, BACK)

        label_cross_xy = MathTex(r"\mathbf{i} \times \mathbf{j} = \mathbf{k}").next_to(arrow_cross_xy, UP)
        label_cross_yz = MathTex(r"\mathbf{j} \times \mathbf{k} = \mathbf{i}").next_to(arrow_cross_yz, LEFT)
        label_cross_zx = MathTex(r"\mathbf{k} \times \mathbf{i} = \mathbf{j}").next_to(arrow_cross_zx, BACK)

        self.play(Write(label_x), Write(label_y), Write(label_z))
        self.wait(1)
        self.play(Write(label_cross_xy), Write(label_cross_yz), Write(label_cross_zx))
        self.wait(2)

        # Clear the scene
        self.clear()
class CrossProductScene(Scene):
    def construct(self):
        axis(self, 3)
        # Define the vectors
        a = np.array([-1, 2, 1])
        b = np.array([1, -2, -1])
        
        # Calculate the cross product
        cross_product = np.cross(a, b)

        # Create arrows for vectors a, b, and their cross product
        vector_a = Arrow(ORIGIN, a, color=BLUE, buff=0)
        vector_b = Arrow(ORIGIN, b, color=RED, buff=0)
        vector_cross = Arrow(ORIGIN, cross_product, color=GREEN, buff=0)

        # Add the arrows to the scene
        self.play(Create(vector_a), Create(vector_b))
        self.wait(1)
        self.play(Create(vector_cross))
        self.wait(2)

        # Add labels for the vectors
        label_a = MathTex(r"\mathbf{a} = [-4, 2, 1]").next_to(vector_a, UP)
        label_b = MathTex(r"\mathbf{b} = [2, 3, -4]").next_to(vector_b, UP)
        label_cross = MathTex(r"\mathbf{a} \times \mathbf{b}").next_to(vector_cross, UP)

        self.play(Write(label_a), Write(label_b))
        self.wait(1)
        self.play(Write(label_cross))
        self.wait(2)

        # Highlight the cross product vector
        self.play(vector_cross.animate.set_color(YELLOW))
        self.wait(2)

        # Clear the scene
        self.clear()
class VectorProjection2(Scene):
    def construct(self):
        axis(self)
        # Define the vectors
        p = np.array([4, 2, 0])
        q = np.array([-1, -3, 0])
        
        # Create the vectors using Arrow
        vector_p = Arrow(ORIGIN, p, color=BLUE, buff=0)
        vector_q = Arrow(ORIGIN, q, color=RED, buff=0)
        
        # Calculate the projection of q onto p
        dot_product = np.dot(p, q)
        p_magnitude_squared = np.dot(p, p)
        proj_q_on_p = (dot_product / p_magnitude_squared) * p

        # Create the projection vector
        projection_vector = Arrow(ORIGIN, proj_q_on_p, color=GREEN, buff=0)

        # Add the vectors to the scene
        self.play(Create(vector_p), Create(vector_q))
        self.wait(1)
        self.play(Create(projection_vector))
        self.wait(2)

        # Adding labels
        label_p = MathTex(r"\mathbf{p} = [4, 2]").next_to(vector_p, UP)
        label_q = MathTex(r"\mathbf{q} = [-1, 3]").next_to(vector_q, UP)
        label_proj = MathTex(r"\text{proj}_{\mathbf{p}} \mathbf{q}").next_to(projection_vector, UP)

        self.play(Write(label_p), Write(label_q))
        self.wait(1)
        self.play(Write(label_proj))
        self.wait(2)

        # Highlight the projection
        self.play(projection_vector.animate.set_color(YELLOW))
        self.wait(2)

        # End scene
        self.clear()
class VectorProjection(Scene):
    def construct(self):
        axis(self)
        # Define vectors v and w
        v = np.array([4, 1, 0])
        w = np.array([2, -1, 0])
        
        # Create vector objects
        vec_v = Arrow(ORIGIN, v, buff=0, color=YELLOW)
        vec_w = Arrow(ORIGIN, w, buff=0, color=PINK)
        
        # Calculate the projection of v onto w
        projection_length = np.dot(v, w) / np.linalg.norm(w)
        proj_w = projection_length * w / np.linalg.norm(w)
        vec_proj_w = Arrow(ORIGIN, proj_w, buff=0, color=GREEN)
        
        # Create labels
        label_v = MathTex(r"\vec{v}", color=YELLOW).next_to(vec_v.get_end(), UP)
        label_w = MathTex(r"\vec{w}", color=PINK).next_to(vec_w.get_end(), DOWN)
        label_proj_w = MathTex(r"\text{Proj}_{\vec{w}} \vec{v}", color=GREEN).next_to(vec_proj_w.get_end(), DOWN)
        
        # Create the grid
        grid = NumberPlane()
        
        # Display objects
        self.play(Create(grid))
        self.play(Create(vec_v), Write(label_v))
        self.play(Create(vec_w), Write(label_w))
        
        # Show the projection
        self.play(Create(vec_proj_w), Write(label_proj_w))
        
        # Show the length of the projection
        length_of_proj = np.dot(v, w) / np.linalg.norm(w)**2
        length_label = MathTex(f"Length = {round(length_of_proj, 2)}").to_edge(UP)
        self.play(Write(length_label))
        
        self.wait(2)

class AngleBetweenLines(Scene):
    def construct(self):
        # Definindo os vetores
        axis(self)
        v_r = np.array([-1, -1, 0])  # Vetor diretor da reta r
        v_s = np.array([3, 6, 0])     # Vetor diretor da reta s

        # Criando os vetores
        vector_r = Arrow(ORIGIN, v_r, color=BLUE)
        vector_s = Arrow(ORIGIN, v_s, color=RED)

        # Adicionando os vetores à cena
        self.add(vector_r, vector_s)

        # Calculando o produto escalar
        dot_product = np.dot(v_r, v_s)

        # Calculando as normas
        norm_r = np.linalg.norm(v_r)
        norm_s = np.linalg.norm(v_s)

        # Calculando o cosseno do ângulo
        cos_theta = dot_product / (norm_r * norm_s)

        # Calculando o ângulo em graus
        theta = np.arccos(cos_theta) * (180 / np.pi)

        # Exibindo o ângulo
        angle_label = MathTex(f"\\theta \\approx {theta:.2f}^\\circ").next_to(vector_r, RIGHT)
        self.add(angle_label)

        # Adicionando o título
        title = Text("Angle Between Lines").to_edge(UP)
        self.add(title)

        # Mostrando a cena
        self.wait(2)

# Para executar, você precisará usar o comando `manim -pql your_file.py AngleBetweenLines`
class SpotlightScene(Scene):
    def construct(self):
        axis(self, 3)
        # Define the spotlight direction and position
        spotlight_direction = np.array([0.5, 0.92, -0.4])
        spotlight_position = np.array([0.0, 1.0, 0.5])
        
        # Create a light cone (represented as a triangle for simplicity)
        cone_base = Circle(radius=2, color=WHITE, fill_opacity=0.5)
        cone_tip = Dot3D(point=spotlight_position, color=YELLOW, radius=0.1)

        # Create a visual representation of the light direction
        light_direction_line = Arrow(
            start=spotlight_position,
            end=spotlight_position + spotlight_direction,
            color=YELLOW,
            buff=0
        )

        # Create a surface to represent the ground
        ground = Square(side_length=4, fill_color=BLUE, fill_opacity=0.5).shift(DOWN)

        # Add elements to the scene
        self.add(ground)
        self.add(cone_base)
        self.add(cone_tip)
        self.add(light_direction_line)

        # Animate the spotlight effect
        self.play(Create(cone_base), Create(cone_tip), Create(light_direction_line))
        self.wait(1)

        # Simulate the spotlight effect by changing the direction
        new_direction = np.array([-0.5, 0.5, -0.4])
        new_light_direction_line = light_direction_line.copy().set_end(spotlight_position + new_direction)

        self.play(Transform(light_direction_line, new_light_direction_line))
        self.wait(1)
class LineAngle(Scene):
    def construct(self):
        axis(self)
        # Definindo os pontos
        point_A = np.array([2, 1, 0])  # Ponto (2, 1)
        point_B = np.array([1, 0, 0])   # Ponto (1, 0)

        # Criando os pontos e as etiquetas
        dot_A = Dot(point_A, color=BLUE)
        dot_B = Dot(point_B, color=RED)
        label_A = MathTex("(2, 1)").next_to(dot_A, UP)
        label_B = MathTex("(1, 0)").next_to(dot_B, DOWN)

        # Criando a linha
        line = Line(point_A, point_A + np.array([1, 1, 0]), color=YELLOW)

        # Adicionando tudo à cena
        self.play(Create(line), Create(dot_A), Create(dot_B), Write(label_A), Write(label_B))
        self.wait(2)

        # Adicionando a equação da reta
        equation = MathTex("y = x - 1").to_edge(UP)
        self.play(Write(equation))
        self.wait(2)
class LineExample(Scene):
    def construct(self):
        axis(self)
        # Criando os pontos A e B
        A = np.array([1, 2, 0])
        B = np.array([3, -1, 0])
        
        # Criando os pontos e as etiquetas
        point_A = Dot(A, color=BLUE)
        point_B = Dot(B, color=RED)
        label_A = MathTex("A(1, 2)").next_to(point_A, UP)
        label_B = MathTex("B(3, -1)").next_to(point_B, DOWN)
        
        # Criando a linha
        line = Line(point_A, point_B, color=YELLOW)
        
        # Adicionando tudo à cena
        self.play(Create(line), Create(point_A), Create(point_B), Write(label_A), Write(label_B))
        self.wait(2)

        # Adicionando a equação da reta
        equation = MathTex("3x + 2y - 7 = 0").to_edge(UP)
        self.play(Write(equation))
        self.wait(2)
class MatrixTransformation(Scene):
    def construct(self):
        axis(self)
        # Define the vector as an array of points
        original_vector = np.array([1, 1, 0])
        transformed_vector = np.array([2, 3, 1])

        # Create the matrix as a MathTex object for display
        matrix_label = MathTex("A = \\begin{pmatrix} 2 & 0 \\\\ 0 & 1 \\end{pmatrix}")
        matrix_label.to_edge(UP)
        
        # Create the vector and transformed vector as Dot objects
        vector = Arrow(ORIGIN, original_vector, buff=0, color=BLUE)
        vector_label = MathTex("\\mathbf{v} = \\begin{pmatrix} 1 \\\\ 1 \\end{pmatrix}")
        vector_label.next_to(matrix_label, DOWN)

        # Display the matrix and the initial vector
        self.play(Write(matrix_label), Write(vector_label), Create(vector))
        self.wait(1)

        # Define the matrix transformation
        def matrix_transform(vector):
            transformation_matrix = np.array([[2, 2], [1, 1]])
            return transformation_matrix @ vector[:2]  # Apply the transformation

        # Transform the vector
        new_vector = Arrow(ORIGIN, transformed_vector, buff=0, color=RED)
        self.play(Transform(vector, new_vector))
        
        # Display the result
        result_label = MathTex("\\mathbf{v'} = \\begin{pmatrix} 2 \\\\ 1 \\end{pmatrix}")
        result_label.next_to(vector_label, DOWN)
        self.play(Write(result_label))
        self.wait(2)

class CartesianMatrixTransformation(Scene):
    def construct(self):
        axes = Axes(
            x_range=(-10, 10),
            y_range=(-10, 10),
            axis_config={"color": BLUE},
        )

        # Create the original vector [2, 4]
        original_vector = Arrow(ORIGIN, [2, 4, 0], color=YELLOW)
        original_label = MathTex(r"\begin{pmatrix} 2 \\ 4 \end{pmatrix}").next_to(original_vector, UP)

        # Create the transformation matrix
        transformation_matrix = Matrix([[-1, -1], [-1, -1]], left_bracket='[', right_bracket=']')
        transformation_label = MathTex(r"\begin{pmatrix} 1 & 1 \\ 1 & 2 \end{pmatrix}").next_to(transformation_matrix, UP)

        # Create the transformed vector [6, 6]
        transformed_vector = Arrow(ORIGIN, [6, 6, 0], color=RED)
        transformed_label = MathTex(r"\begin{pmatrix} 6 \\ 6 \end{pmatrix}").next_to(transformed_vector, UP)

        # Add axes to the scene
        self.play(Create(axes))

        # Display the original vector and label
        self.play(Create(original_vector), Write(original_label))
        
        # Display the transformation matrix
        self.play(Create(transformation_matrix), Write(transformation_label))

        # Perform the transformation animation
        self.play(Transform(original_vector, transformed_vector), Transform(original_label, transformed_label))

        # Show the final transformed vector
        self.wait(2)
# To run this, use the command:
# manim -pql filename.py CartesianMatrixTransformation
class ReflectionExample(Scene):
    def construct(self):
        # Create axes
        axes = Axes(
            x_range=(-10, 10),
            y_range=(-10, 10),
            axis_config={"color": BLUE},
        )

        # Define the incident vector I and normal vector N
        incident_vector = np.array([1, -1, 0])
        normal_vector = np.array([-1, -2, 0])

        # Create arrows for the incident and normal vectors
        incident_arrow = Arrow(ORIGIN, incident_vector, color=YELLOW)
        normal_arrow = Arrow(ORIGIN, normal_vector, color=GREEN)

        # Calculate the reflection vector R
        dot_product = np.dot(incident_vector, normal_vector)
        reflection_vector = incident_vector - 2 * dot_product * (normal_vector / np.linalg.norm(normal_vector))
        
        # Create an arrow for the reflection vector
        reflection_arrow = Arrow(ORIGIN, reflection_vector, color=RED)

        # Add everything to the scene
        self.play(Create(axes))
        self.play(Create(incident_arrow), Create(normal_arrow))
        self.play(Create(reflection_arrow))

        # Add labels
        incident_label = MathTex(r"\mathbf{I}").next_to(incident_arrow, UP)
        normal_label = MathTex(r"\mathbf{N}").next_to(normal_arrow, LEFT)
        reflection_label = MathTex(r"\mathbf{R}").next_to(reflection_arrow, DOWN)

        self.play(Write(incident_label), Write(normal_label), Write(reflection_label))

        # Show the final frame
        self.wait(2)

class DotProductScene(Scene):
    def construct(self):
        # Create the Cartesian plane
        axes = Axes(
            x_range=[-5, 5, 1],
            y_range=[-5, 5, 1],
            axis_config={"color": GREY},
        )

        # Create vectors
        vector_a = Arrow(ORIGIN, np.array([3, 2, 0]), color=BLUE)
        vector_b = Arrow(ORIGIN, np.array([1, -1, 0]), color=RED)

        # Create labels for the vectors
        label_a = MathTex(r'\vec{a} = (9, 7)').next_to(vector_a, UP)
        label_b = MathTex(r'\vec{b} = (1, -1)').next_to(vector_b, DOWN)

        # Display the Cartesian plane and vectors
        self.play(Create(axes))
        self.play(Create(vector_a), Write(label_a))
        self.play(Create(vector_b), Write(label_b))
        
        # Calculate the dot product
        dot_product = 9 * 1 + 7 * (-1)  # 9*1 + 7*(-1) = 2
        dot_product_text = MathTex(r'\vec{a} \cdot \vec{b} = 9 \cdot 1 + 7 \cdot (-1) = 2').to_edge(DOWN)

        # Show the dot product calculation
        self.play(Write(dot_product_text))
        self.wait(2)

        # Highlight the result value
        result_value = MathTex("= 2").next_to(dot_product_text, RIGHT)
        self.play(Write(result_value))

        # Wait before ending the scene
        self.wait(2)

        # End scene
        self.play(FadeOut(vector_a), FadeOut(vector_b), FadeOut(label_a), FadeOut(label_b), FadeOut(dot_product_text), FadeOut(result_value), FadeOut(axes))
        
def axis(self, dimension=2, lim=10):
    if dimension == 2:
        axes = Axes(
            x_range=(-lim, lim),
            y_range=(-lim, lim),
            axis_config={"color": BLUE},
        )
    elif dimension == 3:
        axes = ThreeDAxes(
            x_range=(-lim, lim),
            y_range=(-lim, lim),
            z_range=(-lim, lim),
            axis_config={"color": BLUE},
        )
    else:
        raise ValueError("Dimension must be 2 or 3.")

    self.play(Create(axes))
    return axes
if __name__ == '__main__':
    anim = '' if len(sys.argv) == 1 else sys.argv[1] #input("Animation: ")
    if anim != '':
        anim = ' ' + anim
    subprocess.call(f"manim -pql manim-test.py{anim}")